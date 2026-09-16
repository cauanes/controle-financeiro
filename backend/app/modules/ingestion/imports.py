import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from app.core.config import settings
from app.core.db import audit, get, insert, update
from app.core.errors import DomainError, require
from app.core.money import money
from app.core.schemas import Transaction
from app.modules.ledger import service as ledger
from app.modules.resources import normalize

MAX_SIZE = 20 * 1024 * 1024
MAX_ROWS = 50000


def read_file(data, filename):
    require(0 < len(data) <= MAX_SIZE, "Arquivo vazio ou maior que 20 MB.")
    if data.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            require(
                len(infos) < 2000 and sum(i.file_size for i in infos) <= 100 * 1024 * 1024,
                "XLSX descompactado excede o limite.",
            )
            require(
                not any("vbaProject" in i.filename or "externalLinks/" in i.filename for i in infos),
                "Macros e links externos não são permitidos.",
            )
            require("[Content_Types].xml" in archive.namelist(), "Arquivo XLSX inválido.")
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
        try:
            iterator = book.active.iter_rows(values_only=True)
            headers = [str(v or "").strip() for v in next(iterator)]
            records = []
            for row in iterator:
                require(len(records) < MAX_ROWS, "Arquivo excede 50 mil linhas.")
                require(
                    not any(isinstance(x, str) and x.startswith("=") for x in row),
                    "Fórmulas não são permitidas na importação.",
                )
                records.append(
                    dict(
                        zip(
                            headers,
                            [
                                v.isoformat()
                                if isinstance(v, (date, datetime))
                                else str(v)
                                if v is not None
                                else ""
                                for v in row
                            ],
                        )
                    )
                )
            return "XLSX", records, headers
        finally:
            book.close()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1252")
        except UnicodeDecodeError:
            raise DomainError("Encoding não reconhecido.") from None
    if "<OFX" in text.upper() or text.startswith("OFXHEADER"):
        require(
            "<!ENTITY" not in text.upper() and "<!DOCTYPE" not in text.upper(),
            "Declarações XML externas não são permitidas.",
        )
        records = []
        for block in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.I | re.S):

            def field(name):
                match = re.search(r"<" + name + r">([^<\r\n]*)", block, re.I)
                return match[1].strip() if match else ""

            records.append(
                {
                    "date": field("DTPOSTED")[:8],
                    "amount": field("TRNAMT"),
                    "description": field("MEMO") or field("NAME"),
                    "external_id": field("FITID"),
                }
            )
            require(len(records) <= MAX_ROWS, "Arquivo excede 50 mil linhas.")
        require(records, "OFX não contém lançamentos STMTTRN reconhecidos.")
        return "OFX", records, ["date", "amount", "description", "external_id"]
    require(filename.lower().endswith(".csv"), "Formato não reconhecido. Envie OFX, CSV ou XLSX.")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        raise DomainError("Não foi possível detectar o delimitador CSV.") from None
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    require(reader.fieldnames and len(reader.fieldnames) <= 100, "Cabeçalho CSV inválido.")
    records = []
    for row in reader:
        require(len(records) < MAX_ROWS, "Arquivo excede 50 mil linhas.")
        records.append(row)
    return "CSV", records, list(reader.fieldnames)


def normalize_row(raw, mapping):
    date_format = mapping.get("date_format")
    require(
        date_format in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d"), "Escolha o formato explícito da data."
    )
    raw_date = str(raw.get(mapping.get("date", "date"), "")).strip()
    try:
        day = datetime.strptime(raw_date[:10] if date_format == "%Y-%m-%d" else raw_date, date_format).date()
    except ValueError:
        raise DomainError("Data inválida para o mapeamento escolhido.") from None
    token = str(raw.get(mapping.get("amount", "amount"), "")).strip().replace("R$", "").replace(" ", "")
    locale = mapping.get("locale", "pt-BR")
    require(locale in ("pt-BR", "en-US"), "Locale inválido.")
    token = token.replace(".", "").replace(",", ".") if locale == "pt-BR" else token.replace(",", "")
    value = money(token)
    require(value != 0, "Valor zero não pode ser importado.")
    convention = mapping.get("sign_convention")
    require(convention in ("negative_expense", "positive_expense"), "Escolha a convenção de sinais.")
    expense = value < 0 if convention == "negative_expense" else value > 0
    description = str(raw.get(mapping.get("description", "description"), "")).strip()
    require(description, "Descrição ausente.")
    return {
        "type": "EXPENSE" if expense else "INCOME",
        "amount": format(abs(value), ".2f"),
        "transaction_date": day.isoformat(),
        "description": description[:500],
        "currency": "BRL",
        "external_id": str(raw.get(mapping.get("external_id", "external_id"), "")).strip() or None,
    }


def storage_file(ref):
    base = Path(settings.storage_dir).resolve()
    result = (base / ref).resolve()
    require(result.parent == base, "Referência de arquivo inválida.")
    return result


async def preview(ctx, job, mapping, account_id=None, card_id=None):
    require(job["status"] in ("UPLOADED", "PREVIEW"), "Job não permite novo preview.", "STATE_CONFLICT", 409)
    require(bool(account_id) != bool(card_id), "Selecione uma conta ou cartão.")
    await ledger.active(ctx, "accounts" if account_id else "credit_cards", account_id or card_id)
    # Preview can be regenerated only before decisions, preserving previous rows as skipped.
    old_rows = await ctx.conn.fetch("SELECT id FROM import_rows WHERE import_job_id=$1", job["id"])
    require(not old_rows, "Preview já gerado. Crie outro job para mudar o mapeamento.", "STATE_CONFLICT", 409)
    path = storage_file(job["file_ref"])
    raw = json.loads(path.read_text())
    source = {"kind": "ACCOUNT" if account_id else "CREDIT_CARD", "id": str(account_id or card_id)}
    mapping_hash = hashlib.sha256(json.dumps(mapping, sort_keys=True).encode()).hexdigest()[:16]
    counts = {"ready": 0, "invalid": 0, "duplicate": 0, "review": 0}
    for index, record in enumerate(raw["records"], 1):
        errors = []
        status = "READY"
        normalized = {}
        try:
            normalized = normalize_row(record, mapping)
            normalized["financial_source"] = source
            normalized["status"] = "POSTED"
            if card_id and normalized["type"] != "EXPENSE":
                status = "REVIEW"
                errors.append(
                    "Crédito em extrato de cartão pode ser pagamento ou estorno. Resolva o tipo explicitamente."
                )
            if re.search(
                r"\b(transfer|pagamento.*fatura|pag.*cartao|estorno)", normalize(normalized["description"])
            ):
                status = "REVIEW"
                errors.append(
                    "Possível transferência, pagamento de fatura ou estorno: confirme a classificação."
                )
            from app.modules.categorization.service import categorize

            category = await categorize(ctx, normalized["description"], normalized["type"])
            if category and not category["requires_confirmation"]:
                normalized["category_id"] = category["value"]
        except DomainError as exc:
            errors = [exc.message]
            status = "INVALID"
        identity = normalized.get("external_id")
        namespace = str(account_id or card_id) + ":" + job["format"]
        source_key = (
            namespace + ":external:" + identity
            if identity
            else namespace + ":file:" + job["file_hash"] + ":" + mapping_hash + ":" + str(index)
        )
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    k: normalized.get(k)
                    for k in ("amount", "type", "transaction_date", "description", "financial_source")
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        existing = await ctx.conn.fetchrow(
            "SELECT s.transaction_id,t.status FROM transaction_sources s JOIN transactions t ON t.id=s.transaction_id WHERE s.source_type=$1 AND s.source_key=$2",
            job["format"],
            source_key,
        )
        if existing:
            if existing["status"] == "VOIDED":
                status = "REVIEW"
                errors.append("Origem vinculada a lançamento excluído; revise sem recriar automaticamente.")
            else:
                status = "DUPLICATE"
        row = await insert(
            ctx,
            "import_rows",
            {
                "import_job_id": job["id"],
                "row_number": index,
                "external_id": identity,
                "fingerprint": fingerprint,
                "source_key": source_key,
                "normalized_data": normalized,
                "validation_errors": errors,
                "status": status,
                "transaction_id": existing["transaction_id"] if existing else None,
            },
        )
        if status == "READY":
            from app.modules.reconciliation.service import find_candidates

            matches = await find_candidates(ctx, row)
            if matches:
                status = "REVIEW"
                await update(ctx, "import_rows", row["id"], {"status": status})
        counts[status.lower()] += 1
    result = await update(
        ctx,
        "import_jobs",
        job["id"],
        {
            "status": "PREVIEW",
            "mapping": mapping,
            "target_account_id": account_id,
            "target_credit_card_id": card_id,
            "counts": counts,
        },
    )
    await audit(ctx, "PREVIEW", "import_jobs", result)
    return result


async def execute_job(ctx, job_id):
    job = await get(ctx, "import_jobs", job_id, lock=True)
    if job["status"] == "COMPLETED":
        return job
    ctx.user_id = job["confirmed_by"]
    member = await ctx.conn.fetchrow(
        "SELECT role FROM household_members WHERE user_id=$1 AND status='ACTIVE'", ctx.user_id
    )
    require(member and member["role"] != "VIEWER", "Importador não possui mais acesso.", "FORBIDDEN", 403)
    ctx.role = member["role"]
    ctx.origin = job["format"]
    decisions = job["counts"].get("decisions", [])
    failures = []
    for decision in decisions:
        row = await get(ctx, "import_rows", decision["row_id"], lock=True)
        if row["status"] in ("IMPORTED", "RECONCILED", "DUPLICATE", "SKIPPED"):
            continue
        try:
            async with ctx.conn.transaction():
                if decision["action"] == "SKIP":
                    await update(ctx, "import_rows", row["id"], {"status": "SKIPPED"})
                    continue
                if decision["action"] == "RECONCILE":
                    from app.modules.reconciliation.service import accept

                    match = await get(ctx, "transaction_matches", decision["match_id"])
                    require(match["import_row_id"] == row["id"], "Match não corresponde à linha.")
                    await accept(ctx, match["id"], decision["expected_transaction_version"])
                    continue
                require(
                    row["status"] in ("READY", "REVIEW") and not row["validation_errors"],
                    "Resolva erros da linha antes de importar.",
                )
                values = {k: v for k, v in row["normalized_data"].items() if k in Transaction.model_fields}
                # Conflict after preview must never duplicate a source.
                existing = await ctx.conn.fetchrow(
                    "SELECT transaction_id FROM transaction_sources WHERE source_type=$1 AND source_key=$2",
                    job["format"],
                    row["source_key"],
                )
                if existing:
                    tx = await get(ctx, "transactions", existing["transaction_id"])
                    require(tx["status"] != "VOIDED", "Origem vinculada a lançamento excluído.")
                    await update(
                        ctx, "import_rows", row["id"], {"status": "DUPLICATE", "transaction_id": tx["id"]}
                    )
                    continue
                result = await ledger.create(
                    ctx,
                    Transaction.model_validate(values),
                    source_type=job["format"],
                    source_key=row["source_key"],
                    metadata={"import_row_id": row["id"], "external_id": row["external_id"]},
                )
                await update(
                    ctx, "import_rows", row["id"], {"status": "IMPORTED", "transaction_id": result["id"]}
                )
        except (
            DomainError,
            __import__("pydantic").ValidationError,
            __import__("asyncpg").IntegrityConstraintViolationError,
        ) as exc:
            failures.append(
                {
                    "row_id": str(row["id"]),
                    "message": exc.message
                    if isinstance(exc, DomainError)
                    else "Linha inválida ou em conflito.",
                }
            )
    all_rows = await ctx.conn.fetch("SELECT status FROM import_rows WHERE import_job_id=$1", job["id"])
    counts = {
        status: sum(r["status"] == status for r in all_rows)
        for status in ("IMPORTED", "RECONCILED", "DUPLICATE", "SKIPPED", "INVALID", "READY", "REVIEW")
    }
    counts["decisions"] = decisions
    unfinished = any(r["status"] in ("READY", "REVIEW", "INVALID") for r in all_rows)
    return await update(
        ctx,
        "import_jobs",
        job["id"],
        {
            "status": "PARTIAL" if failures or unfinished else "COMPLETED",
            "counts": counts,
            "errors": failures,
        },
    )
