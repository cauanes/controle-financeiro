import base64
import json
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Header, Query

from app.core.auth import Ctx
from app.core.db import get, idempotent, wire
from app.core.errors import require
from app.core.schemas import Patch, Transaction, Version
from app.modules.ledger import service

router = APIRouter(prefix="/api/v1", tags=["ledger"])


@router.post("/transactions", status_code=201)
async def create_transaction(body: Transaction, ctx: Ctx, idempotency_key: str = Header()):
    return await idempotent(
        ctx, "transactions:create", idempotency_key, body.model_dump(), lambda: service.create(ctx, body)
    )


@router.get("/transactions")
async def list_transactions(
    ctx: Ctx,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    date_basis: str = "transaction",
    type: str | None = None,
    status: str | None = None,
    account_id: UUID | None = None,
    card_id: UUID | None = None,
    category_id: UUID | None = None,
    responsible_user_id: UUID | None = None,
    merchant_id: UUID | None = None,
    source_type: str | None = None,
    reconciliation_status: str | None = None,
    q: str | None = None,
    min_amount: str | None = None,
    max_amount: str | None = None,
    include_descendants: bool = True,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
):
    require(date_basis in ("transaction", "competence"), "Base de data inválida.")
    field = "transaction_date" if date_basis == "transaction" else "competence_date"
    params = []
    conditions = []

    def add(sql, value):
        params.append(value)
        conditions.append(sql.replace("?", f"${len(params)}"))

    if from_:
        add(f"t.{field}>=?", from_)
    if to:
        add(f"t.{field}<=?", to)
    if from_ and to:
        require(from_ <= to, "Período inválido.")
    for col, value in [
        ("type", type),
        ("status", status),
        ("credit_card_id", card_id),
        ("responsible_user_id", responsible_user_id),
        ("merchant_id", merchant_id),
        ("reconciliation_status", reconciliation_status),
    ]:
        if value is not None:
            add(f"t.{col}=?", value)
    if account_id:
        add("(t.account_id=? OR t.destination_account_id=?)", account_id)
    if category_id:
        await get(ctx, "categories", category_id)
        if include_descendants:
            add(
                "t.category_id IN (WITH RECURSIVE tree AS (SELECT id FROM categories WHERE id=? UNION ALL SELECT c.id FROM categories c JOIN tree ON c.parent_id=tree.id) SELECT id FROM tree)",
                category_id,
            )
        else:
            add("t.category_id=?", category_id)
    if q:
        add("t.description ILIKE ?", f"%{q[:200]}%")
    if source_type:
        add(
            "EXISTS(SELECT 1 FROM transaction_sources s WHERE s.transaction_id=t.id AND s.source_type=?)",
            source_type,
        )
    from app.core.money import money

    if min_amount is not None:
        add("t.amount>=?", money(min_amount))
    if max_amount is not None:
        add("t.amount<=?", money(max_amount))
    if cursor:
        try:
            d, id = json.loads(base64.urlsafe_b64decode(cursor))
            add(f"(t.{field},t.id)<(?,", date.fromisoformat(d))
            params.append(UUID(id))
            conditions[-1] += f"${len(params)})"
        except (ValueError, TypeError):
            require(False, "Cursor inválido.")
    sql = "SELECT t.*,COALESCE((SELECT jsonb_agg(jsonb_build_object('source_type',s.source_type,'id',s.id)) FROM transaction_sources s WHERE s.transaction_id=t.id),'[]'::jsonb) AS sources FROM transactions t"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += f" ORDER BY t.{field} DESC,t.id DESC LIMIT {limit + 1}"
    result = [dict(r) for r in await ctx.conn.fetch(sql, *params)]
    next_cursor = None
    if len(result) > limit:
        result = result[:limit]
        last = result[-1]
        next_cursor = base64.urlsafe_b64encode(
            json.dumps([last[field].isoformat(), str(last["id"])]).encode()
        ).decode()
    return wire({"data": result, "next_cursor": next_cursor})


@router.get("/transactions/{id}")
async def detail(id: UUID, ctx: Ctx):
    result = await get(ctx, "transactions", id)
    result["sources"] = [
        dict(r) for r in await ctx.conn.fetch("SELECT * FROM transaction_sources WHERE transaction_id=$1", id)
    ]
    return wire(result)


@router.patch("/transactions/{id}")
async def edit(id: UUID, body: Patch, ctx: Ctx):
    return wire(await service.patch(ctx, id, body.changes, body.expected_version))


@router.delete("/transactions/{id}")
async def delete(
    id: UUID, ctx: Ctx, expected_version: int, reason: str = Query(min_length=1, max_length=500)
):
    return wire(await service.void(ctx, id, expected_version, reason))


@router.post("/transactions/{id}/post")
async def post(id: UUID, body: Version, ctx: Ctx):
    tx = await get(ctx, "transactions", id)
    require(tx["status"] == "PLANNED", "Lançamento não está previsto.")
    require(tx["transaction_date"] <= ctx.today(), "Confirme a data real antes de marcar como pago.")
    return wire(await service.patch(ctx, id, {"status": "POSTED"}, body.expected_version))


@router.get("/transactions/{id}/audit")
async def history(id: UUID, ctx: Ctx):
    await get(ctx, "transactions", id)
    return wire(
        {
            "data": [
                dict(r)
                for r in await ctx.conn.fetch(
                    "SELECT * FROM audit_logs WHERE entity_id=$1 ORDER BY occurred_at", id
                )
            ]
        }
    )
