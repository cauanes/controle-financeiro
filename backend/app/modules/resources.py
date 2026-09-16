import unicodedata
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter

from app.core import schemas
from app.core.auth import Ctx
from app.core.db import audit, get, insert, rows, update, wire
from app.core.errors import require
from app.modules.ledger.service import account_balances, active, invoice_balance

router = APIRouter(prefix="/api/v1", tags=["resources"])
RESOURCES = {
    "accounts": ("accounts", schemas.Account, False),
    "categories": ("categories", schemas.Category, True),
    "merchants": ("merchants", schemas.Merchant, False),
    "cards": ("credit_cards", schemas.Card, False),
    "category-rules": ("category_rules", schemas.Rule, True),
    "merchant-rules": ("merchant_rules", schemas.MerchantRule, True),
    "goals": ("goals", schemas.Goal, False),
    "assets": ("assets", schemas.Asset, False),
    "liabilities": ("liabilities", schemas.Liability, False),
    "alert-rules": ("alert_rules", schemas.AlertRule, False),
}


def normalize(text):
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.lower().strip()) if not unicodedata.combining(c)
    )


async def prepare(ctx, table, body, existing=None):
    values = body.model_dump()
    for key in ("name", "pattern"):
        if key in values:
            values[key] = values[key].strip()
            require(values[key], f"{key} não pode ficar vazio.")
    for field, target in {
        "parent_id": "categories",
        "category_id": "categories",
        "merchant_id": "merchants",
        "default_payment_account_id": "accounts",
        "linked_account_id": "accounts",
        "linked_credit_card_id": "credit_cards",
    }.items():
        if values.get(field):
            await active(ctx, target, values[field])
    if table == "categories" and values.get("parent_id"):
        parent = await get(ctx, "categories", values["parent_id"])
        require(parent["kind"] == values["kind"], "Pai e filha devem ter o mesmo tipo.")
        seen = {existing["id"]} if existing else set()
        while parent:
            require(parent["id"] not in seen, "Hierarquia circular de categorias.")
            seen.add(parent["id"])
            parent = await get(ctx, "categories", parent["parent_id"]) if parent["parent_id"] else None
    if table == "categories" and existing and values["kind"] != existing["kind"]:
        used = await ctx.conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM transactions WHERE category_id=$1) OR EXISTS(SELECT 1 FROM categories WHERE parent_id=$1)",
            existing["id"],
        )
        require(not used, "Categoria em uso não pode mudar de tipo.")
    if table == "merchants":
        values["normalized_name"] = normalize(values["name"])
    for field in ("valuation", "outstanding_amount", "limit_amount"):
        if values.get(field) is not None:
            require(values[field] >= 0, "Valor não pode ser negativo.")
    if table == "accounts" and existing:
        if any(values[k] != existing[k] for k in ("opening_balance", "opening_balance_date")):
            used = await ctx.conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM transactions WHERE account_id=$1 OR destination_account_id=$1)",
                existing["id"],
            )
            require(not used, "Saldo de abertura de conta em uso exige ajuste financeiro explícito.")
    if table == "category_rules" and values.get("user_id"):
        require(values["user_id"] == ctx.user_id, "Regra pessoal deve pertencer ao próprio usuário.")
    if table == "alert_rules":
        member = await ctx.conn.fetchval(
            "SELECT id FROM household_members WHERE user_id=$1 AND status='ACTIVE'",
            values["recipient_user_id"],
        )
        require(member, "Destinatário inválido.")
        require(
            values["recipient_user_id"] == ctx.user_id,
            "Preferências de alerta devem ser configuradas pelo destinatário.",
        )
        quiet = values["quiet_hours"]
        require(
            set(quiet) == {"start", "end"}
            and all(isinstance(quiet[k], int) and 0 <= quiet[k] <= 23 for k in quiet),
            "Horário de silêncio inválido.",
        )
        allowed = {"threshold", "budget_id", "minimum_balance"}
        require(set(values["config"]) <= allowed, "Configuração de alerta desconhecida.")
        if "budget_id" in values["config"]:
            await get(ctx, "budgets", values["config"]["budget_id"])
    return values


def register(path, table, model, admin):
    async def listing(ctx: Ctx):
        result = await account_balances(ctx) if table == "accounts" else await rows(ctx, table)
        return wire({"data": result, "next_cursor": None})

    async def detail(id: UUID, ctx: Ctx):
        return wire(await get(ctx, table, id))

    async def creating(body, ctx: Ctx):
        ctx.write(admin=admin)
        values = await prepare(ctx, table, body)
        record = await insert(ctx, table, values)
        await audit(ctx, "CREATE", table, record)
        return wire(record)

    creating.__annotations__["body"] = model

    async def editing(id: UUID, body: schemas.Patch, ctx: Ctx):
        ctx.write(admin=admin)
        old = await get(ctx, table, id)
        require(set(body.changes) <= set(model.model_fields), "Campos de alteração inválidos.")
        current = {k: old[k] for k in model.model_fields if k in old}
        values = await prepare(ctx, table, model.model_validate(current | body.changes), old)
        record = await update(ctx, table, id, values, expected_version=body.expected_version)
        await audit(ctx, "UPDATE", table, record, old)
        return wire(record)

    async def archive(id: UUID, body: schemas.Version, ctx: Ctx):
        ctx.write(admin=admin)
        old = await get(ctx, table, id)
        require("archived_at" in old, "Este recurso não suporta arquivamento.")
        record = await update(
            ctx,
            table,
            id,
            {"archived_at": datetime.now(timezone.utc)},
            expected_version=body.expected_version,
        )
        await audit(ctx, "ARCHIVE", table, record, old)
        return wire(record)

    for method, suffix, func in [
        ("GET", "", listing),
        ("GET", "/{id}", detail),
        ("POST", "", creating),
        ("PATCH", "/{id}", editing),
        ("POST", "/{id}/archive", archive),
    ]:
        router.add_api_route(
            "/" + path + suffix,
            func,
            methods=[method],
            name=method + "_" + table + suffix,
            status_code=201 if method == "POST" and suffix == "" else 200,
        )


for path, (table, model, admin) in RESOURCES.items():
    register(path, table, model, admin)


@router.get("/invoices")
async def invoices(ctx: Ctx):
    result = []
    for inv in await rows(ctx, "credit_card_invoices"):
        result.append(inv | {"balance": await invoice_balance(ctx, inv["id"])})
    return wire({"data": result})


@router.get("/invoices/{id}")
async def invoice(id: UUID, ctx: Ctx):
    inv = await get(ctx, "credit_card_invoices", id)
    return wire(
        inv
        | {
            "balance": await invoice_balance(ctx, id),
            "transactions": [
                dict(r)
                for r in await ctx.conn.fetch(
                    "SELECT * FROM transactions WHERE invoice_id=$1 ORDER BY transaction_date", id
                )
            ],
        }
    )


@router.patch("/invoices/{id}")
async def change_invoice(id: UUID, body: schemas.Patch, ctx: Ctx):
    from datetime import date

    ctx.write()
    require(set(body.changes) <= {"closing_date", "due_date"}, "Somente datas da fatura podem ser ajustadas.")
    old = await get(ctx, "credit_card_invoices", id)
    values = {k: date.fromisoformat(v) for k, v in body.changes.items()}
    record = await update(ctx, "credit_card_invoices", id, values, expected_version=body.expected_version)
    require(
        record["period_start"] <= record["closing_date"] < record["due_date"], "Datas de fatura inválidas."
    )
    await audit(ctx, "UPDATE", "credit_card_invoices", record, old)
    return wire(record)


class Payment(schemas.Strict):
    account_id: UUID
    amount: schemas.PositiveMoney
    transaction_date: __import__("datetime").date


@router.post("/invoices/{id}/payments", status_code=201)
async def pay(id: UUID, body: Payment, ctx: Ctx, idempotency_key: str = __import__("fastapi").Header()):
    from app.core.db import idempotent
    from app.modules.ledger.service import create

    tx = schemas.Transaction(
        type="TRANSFER",
        amount=body.amount,
        transaction_date=body.transaction_date,
        description="Pagamento de fatura",
        financial_source=schemas.Source(kind="INVOICE_PAYMENT", account_id=body.account_id, invoice_id=id),
    )
    return await idempotent(
        ctx, "invoice:payment:" + str(id), idempotency_key, body.model_dump(), lambda: create(ctx, tx)
    )
