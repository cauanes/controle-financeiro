import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Header, UploadFile
from pydantic import Field

from app.core.auth import Ctx
from app.core.config import settings
from app.core.db import audit, emit, get, idempotent, insert, rows, update, wire
from app.core.errors import require
from app.core.schemas import Patch, Strict, Transaction, Version
from app.modules.categorization.merchant_classifier import classify_merchant
from app.modules.ingestion import imports
from app.modules.ingestion.invoice_parser import parse_invoice
from app.modules.ingestion.ocr import extract_text_from_image
from app.modules.reconciliation import service as reconciliation

router = APIRouter(prefix="/api/v1", tags=["imports"])


class Preview(Strict):
    expected_version: int
    mapping: dict
    account_id: UUID | None = None
    card_id: UUID | None = None
    template_id: UUID | None = None


class Decision(Strict):
    row_id: UUID
    action: str
    match_id: UUID | None = None
    expected_transaction_version: int | None = None


class Confirm(Strict):
    expected_version: int
    decisions: list[Decision] = Field(max_length=50000)


class Template(Strict):
    name: str = Field(min_length=1, max_length=100)
    format: str
    mapping: dict


@router.post("/imports", status_code=201)
async def upload(ctx: Ctx, file: UploadFile = File()):
    data = await file.read(imports.MAX_SIZE + 1)
    kind, records, headers = imports.read_file(data, file.filename or "")
    require(records, "Arquivo sem linhas.")
    ref = uuid4().hex + ".json"
    base = Path(settings.storage_dir)
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(base / ref, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump({"records": records, "headers": headers}, output)
        job = await insert(
            ctx,
            "import_jobs",
            {
                "file_hash": hashlib.sha256(data).hexdigest(),
                "file_ref": ref,
                "format": kind,
                "status": "UPLOADED",
            },
        )
        await audit(ctx, "UPLOAD", "import_jobs", job)
    except Exception:
        (base / ref).unlink(missing_ok=True)
        raise
    return wire(job | {"headers": headers, "sample": records[:5]})


@router.post("/imports/invoice-image")
async def process_invoice_image(ctx: Ctx, file: UploadFile = File()):
    data = await file.read(20 * 1024 * 1024 + 1)
    ocr_text = extract_text_from_image(data, file.content_type)
    invoice = parse_invoice(ocr_text)
    
    classified_txs = []
    for tx in invoice.transactions:
        cat_info = await classify_merchant(ctx, tx.description)
        tx_dict = {
            "date": tx.date,
            "description": tx.description,
            "amount": tx.amount,
            "type": tx.type,
            "installment_current": tx.installment_current,
            "installment_total": tx.installment_total,
            "card": {
                "type": tx.card.type,
                "last4": tx.card.last4,
                "holder": tx.card.holder
            } if tx.card else None,
            "category_name": cat_info["category_name"],
            "category_id": cat_info.get("category_id"),
            "confidence": cat_info.get("confidence", 0.9)
        }
        classified_txs.append(tx_dict)
        
    return {
        "summary": {
            "total_amount": invoice.summary.total_amount,
            "due_date": invoice.summary.due_date,
            "closing_date": invoice.summary.closing_date,
            "available_limit": invoice.summary.available_limit,
            "total_limit": invoice.summary.total_limit,
            "paid_amount": invoice.summary.paid_amount,
            "issuer": invoice.summary.issuer
        },
        "transactions": classified_txs,
        "raw_text": ocr_text
    }


@router.get("/imports")
async def jobs(ctx: Ctx):
    return wire(
        {
            "data": [
                {k: v for k, v in job.items() if k != "file_ref"} for job in await rows(ctx, "import_jobs")
            ]
        }
    )


@router.get("/imports/{id}")
async def job_detail(id: UUID, ctx: Ctx):
    job = await get(ctx, "import_jobs", id)
    return wire({k: v for k, v in job.items() if k != "file_ref"})


@router.get("/imports/{id}/rows")
async def job_rows(id: UUID, ctx: Ctx):
    await get(ctx, "import_jobs", id)
    return wire(
        {
            "data": [
                dict(r)
                for r in await ctx.conn.fetch(
                    "SELECT * FROM import_rows WHERE import_job_id=$1 ORDER BY row_number", id
                )
            ]
        }
    )


@router.post("/imports/{id}/preview")
async def preview(id: UUID, body: Preview, ctx: Ctx):
    job = await get(ctx, "import_jobs", id)
    require(job["version"] == body.expected_version, "Job mudou. Recarregue.", "VERSION_CONFLICT", 409)
    mapping = body.mapping
    if body.template_id:
        template = await get(ctx, "import_templates", body.template_id)
        require(template["format"] == job["format"], "Template de outro formato.")
        mapping = template["mapping"]
    return wire(await imports.preview(ctx, job, mapping, body.account_id, body.card_id))


@router.patch("/imports/{id}/rows/{row_id}")
async def resolve_row(id: UUID, row_id: UUID, body: Patch, ctx: Ctx):
    job = await get(ctx, "import_jobs", id)
    require(job["status"] in ("PREVIEW", "PARTIAL"), "Job não permite corrigir linha.")
    row = await get(ctx, "import_rows", row_id)
    require(
        row["import_job_id"] == id and row["status"] in ("INVALID", "READY", "REVIEW"),
        "Linha não pode ser alterada.",
    )
    require(set(body.changes) <= set(Transaction.model_fields), "Campos inválidos.")
    values = {k: v for k, v in row["normalized_data"].items() if k in Transaction.model_fields} | body.changes
    transaction = Transaction.model_validate(values)
    from app.modules.ledger.service import validate

    await validate(ctx, transaction)
    after = await update(
        ctx,
        "import_rows",
        row_id,
        {"normalized_data": wire(transaction.model_dump()), "validation_errors": [], "status": "READY"},
        expected_version=body.expected_version,
    )
    await ctx.conn.execute(
        "UPDATE transaction_matches SET status='STALE' WHERE import_row_id=$1 AND status='PROPOSED'", row_id
    )
    await audit(ctx, "RESOLVE", "import_rows", after, row)
    return wire(after)


@router.post("/imports/{id}/confirm", status_code=202)
async def confirm(id: UUID, body: Confirm, ctx: Ctx, idempotency_key: str = Header()):
    async def execute():
        job = await get(ctx, "import_jobs", id)
        require(job["version"] == body.expected_version, "Job mudou. Recarregue.", "VERSION_CONFLICT", 409)
        require(
            job["status"] in ("PREVIEW", "PARTIAL"), "Job não pode ser confirmado.", "STATE_CONFLICT", 409
        )
        seen = set()
        for decision in body.decisions:
            require(decision.row_id not in seen, "Decisão de linha repetida.")
            seen.add(decision.row_id)
            row = await get(ctx, "import_rows", decision.row_id)
            require(row["import_job_id"] == id, "Linha de outro job.")
            require(decision.action in ("IMPORT", "RECONCILE", "SKIP"), "Decisão inválida.")
            if decision.action == "IMPORT":
                require(
                    not row["validation_errors"] and row["status"] in ("READY", "REVIEW"),
                    "Resolva a linha antes de importar.",
                )
            if decision.action == "RECONCILE":
                require(
                    decision.match_id and decision.expected_transaction_version,
                    "Selecione uma proposta e sua versão.",
                )
                match = await get(ctx, "transaction_matches", decision.match_id)
                require(match["import_row_id"] == decision.row_id, "Proposta não corresponde à linha.")
        pending = await ctx.conn.fetch(
            "SELECT id FROM import_rows WHERE import_job_id=$1 AND status NOT IN ($2,$3,$4,$5)",
            id,
            "IMPORTED",
            "RECONCILED",
            "DUPLICATE",
            "SKIPPED",
        )
        require({r["id"] for r in pending} <= seen, "Decida o destino de todas as linhas pendentes.")
        result = await update(
            ctx,
            "import_jobs",
            id,
            {
                "status": "PROCESSING",
                "counts": job["counts"] | {"decisions": wire([d.model_dump() for d in body.decisions])},
                "confirmed_by": ctx.user_id,
                "confirmed_at": datetime.now(timezone.utc),
            },
        )
        await emit(ctx, "ImportConfirmed", id)
        return result

    return await idempotent(ctx, "imports:confirm:" + str(id), idempotency_key, body.model_dump(), execute)


@router.post("/imports/{id}/cancel")
async def cancel(id: UUID, body: Version, ctx: Ctx):
    job = await get(ctx, "import_jobs", id)
    require(job["status"] in ("UPLOADED", "PREVIEW"), "Importação já começou.", "STATE_CONFLICT", 409)
    return wire(
        await update(ctx, "import_jobs", id, {"status": "CANCELLED"}, expected_version=body.expected_version)
    )


@router.get("/import-templates")
async def templates(ctx: Ctx):
    return wire({"data": await rows(ctx, "import_templates")})


@router.get("/import-templates/{id}")
async def template_detail(id: UUID, ctx: Ctx):
    return wire(await get(ctx, "import_templates", id))


@router.post("/import-templates", status_code=201)
async def template_create(body: Template, ctx: Ctx):
    require(body.format in ("CSV", "OFX", "XLSX"), "Formato inválido.")
    version = await ctx.conn.fetchval(
        "SELECT COALESCE(max(version),0)+1 FROM import_templates WHERE name=$1", body.name
    )
    result = await insert(
        ctx, "import_templates", body.model_dump() | {"version": version, "user_id": ctx.user_id}
    )
    await audit(ctx, "CREATE", "import_templates", result)
    return wire(result)


@router.get("/reconciliation")
async def matches(ctx: Ctx):
    return wire(
        {
            "data": [
                dict(r)
                for r in await ctx.conn.fetch(
                    "SELECT m.*,to_jsonb(t) AS transaction,to_jsonb(r) AS import_row FROM transaction_matches m JOIN transactions t ON t.id=m.transaction_id JOIN import_rows r ON r.id=m.import_row_id WHERE m.status IN ('PROPOSED','STALE') ORDER BY m.score DESC"
                )
            ]
        }
    )


@router.post("/reconciliation/{id}/accept")
async def accept(id: UUID, body: Version, ctx: Ctx, idempotency_key: str = Header()):
    return await idempotent(
        ctx,
        "reconcile:" + str(id),
        idempotency_key,
        body.model_dump(),
        lambda: reconciliation.accept(ctx, id, body.expected_version),
    )


@router.post("/reconciliation/{id}/reject")
async def reject(id: UUID, ctx: Ctx):
    return wire(await reconciliation.reject(ctx, id))
