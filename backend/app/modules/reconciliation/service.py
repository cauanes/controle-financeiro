from datetime import date, datetime, timezone
from decimal import Decimal
from difflib import SequenceMatcher

from app.core.db import audit, emit, get, insert, update
from app.core.errors import require
from app.modules.ledger.service import add_source
from app.modules.resources import normalize


def compatible(tx, data):
    source = data.get("financial_source", {})
    source_id = tx["credit_card_id"] if source.get("kind") == "CREDIT_CARD" else tx["account_id"]
    return (
        tx["status"] != "VOIDED"
        and tx["type"] == data.get("type")
        and tx["subtype"] is None
        and str(source_id) == source.get("id")
        and tx["currency"] == data.get("currency", "BRL")
        and tx["amount"] == Decimal(data["amount"])
        and abs((tx["transaction_date"] - date.fromisoformat(data["transaction_date"])).days) <= 3
        and not tx["installment_group_id"]
    )


async def find_candidates(ctx, row):
    data = row["normalized_data"]
    txs = await ctx.conn.fetch(
        "SELECT * FROM transactions WHERE amount=$1 AND type=$2 AND transaction_date BETWEEN $3::date-3 AND $3::date+3 AND status<>'VOIDED'",
        Decimal(data["amount"]),
        data["type"],
        date.fromisoformat(data["transaction_date"]),
    )
    results = []
    for raw in txs:
        tx = dict(raw)
        if not compatible(tx, data):
            continue
        days = abs((tx["transaction_date"] - date.fromisoformat(data["transaction_date"])).days)
        description = SequenceMatcher(
            None, normalize(tx["description"]), normalize(data["description"])
        ).ratio()
        merchant = 1 if data.get("merchant_id") and str(tx["merchant_id"]) == data["merchant_id"] else 0
        features = {
            "amount": 1,
            "source": 1,
            "date": 1 - days / 4,
            "merchant": merchant,
            "description": description,
            "algorithm_version": "1",
        }
        score = Decimal(
            str(0.4 + 0.25 + 0.15 * features["date"] + 0.1 * merchant + 0.1 * description)
        ).quantize(Decimal(".0001"))
        if score < Decimal(".75"):
            continue
        old = await ctx.conn.fetchrow(
            "SELECT * FROM transaction_matches WHERE transaction_id=$1 AND import_row_id=$2",
            tx["id"],
            row["id"],
        )
        if old:
            if old["status"] != "REJECTED":
                results.append(dict(old))
            continue
        match = await insert(
            ctx,
            "transaction_matches",
            {
                "transaction_id": tx["id"],
                "import_row_id": row["id"],
                "score": score,
                "score_details": features,
                "status": "PROPOSED",
                "transaction_version": tx["version"],
            },
        )
        results.append(match)
    return results


async def accept(ctx, id, expected_version):
    ctx.write()
    await ctx.lock()
    match = await get(ctx, "transaction_matches", id, lock=True)
    if match["status"] == "ACCEPTED":
        return match
    require(match["status"] == "PROPOSED", "Proposta não está disponível.", "STATE_CONFLICT", 409)
    row = await get(ctx, "import_rows", match["import_row_id"], lock=True)
    tx = await get(ctx, "transactions", match["transaction_id"], lock=True)
    require(
        tx["version"] == expected_version == match["transaction_version"],
        "Candidato mudou. Recalcule a proposta.",
        "VERSION_CONFLICT",
        409,
    )
    require(row["status"] in ("READY", "REVIEW"), "Linha já resolvida.", "STATE_CONFLICT", 409)
    require(compatible(tx, row["normalized_data"]), "Valor, data, tipo ou fonte incompatíveis.")
    job = await get(ctx, "import_jobs", row["import_job_id"])
    await add_source(
        ctx,
        tx,
        job["format"],
        row["source_key"],
        {"import_row_id": row["id"], "external_id": row["external_id"]},
    )
    result = await update(
        ctx,
        "transaction_matches",
        id,
        {"status": "ACCEPTED", "decided_by": ctx.user_id, "decided_at": datetime.now(timezone.utc)},
    )
    await update(ctx, "import_rows", row["id"], {"status": "RECONCILED", "transaction_id": tx["id"]})
    after = await update(ctx, "transactions", tx["id"], {"reconciliation_status": "RECONCILED"})
    await audit(ctx, "RECONCILE", "transactions", after, tx)
    await emit(ctx, "TransactionReconciled", tx["id"])
    return result


async def reject(ctx, id):
    match = await get(ctx, "transaction_matches", id)
    require(match["status"] in ("PROPOSED", "REJECTED"), "Proposta já encerrada.", "STATE_CONFLICT", 409)
    after = await update(
        ctx,
        "transaction_matches",
        id,
        {"status": "REJECTED", "decided_by": ctx.user_id, "decided_at": datetime.now(timezone.utc)},
    )
    await audit(ctx, "REJECT", "transaction_matches", after, match)
    return after
