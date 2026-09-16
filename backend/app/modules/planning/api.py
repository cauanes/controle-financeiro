from datetime import date
from uuid import UUID

from fastapi import APIRouter, Header

from app.core.auth import Ctx
from app.core.db import audit, get, idempotent, insert, rows, update, wire
from app.core.errors import require
from app.core.schemas import Budget, Contribution, Patch, Recurring
from app.modules.planning import service

router = APIRouter(prefix="/api/v1", tags=["planning"])


@router.get("/budgets")
async def budgets(ctx: Ctx):
    return wire({"data": [await service.budget_detail(ctx, b["id"]) for b in await rows(ctx, "budgets")]})


@router.get("/budgets/{id}")
async def budget(id: UUID, ctx: Ctx):
    return wire(await service.budget_detail(ctx, id))


@router.post("/budgets", status_code=201)
async def create_budget(body: Budget, ctx: Ctx):
    return wire(await service.create_budget(ctx, body))


@router.patch("/budgets/{id}")
async def edit_budget(id: UUID, body: Patch, ctx: Ctx):
    old = await service.budget_detail(ctx, id)
    require(set(body.changes) <= set(Budget.model_fields), "Campos de orçamento inválidos.")
    current = {k: v for k, v in old.items() if k in Budget.model_fields}
    current["categories"] = [
        {k: v for k, v in line.items() if k in ("category_id", "amount")} for line in old["categories"]
    ]
    data = Budget.model_validate(current | body.changes)
    await service.validate_budget(ctx, data, id)
    result = await update(
        ctx, "budgets", id, data.model_dump(exclude={"categories"}), expected_version=body.expected_version
    )
    await ctx.conn.execute("DELETE FROM budget_categories WHERE budget_id=$1", id)
    for line in data.categories:
        await insert(ctx, "budget_categories", {"budget_id": id, **line.model_dump()})
    await audit(
        ctx,
        "UPDATE",
        "budgets",
        result | {"categories": wire([line.model_dump() for line in data.categories])},
        old,
    )
    return wire(await service.budget_detail(ctx, id))


@router.get("/recurring")
async def recurring(ctx: Ctx):
    return wire({"data": await rows(ctx, "recurring_transactions")})


@router.get("/recurring/{id}")
async def recurring_detail(id: UUID, ctx: Ctx):
    return wire(await get(ctx, "recurring_transactions", id))


@router.post("/recurring", status_code=201)
async def create_recurring(body: Recurring, ctx: Ctx):
    return wire(await service.create_recurring(ctx, body))


@router.patch("/recurring/{id}")
async def edit_recurring(id: UUID, body: Patch, ctx: Ctx):
    old = await get(ctx, "recurring_transactions", id)
    require(
        set(body.changes) <= {"enabled", "end_date", "template", "cost_class"},
        "Para mudar o calendário, pause e crie uma nova recorrência.",
    )
    model = Recurring.model_validate(
        {k: v for k, v in old.items() if k in Recurring.model_fields} | body.changes
    )
    from app.modules.ledger.service import validate

    await validate(ctx, model.template)
    require(model.template.installment_count == 1, "Recorrência parcelada não suportada.")
    values = {k: v for k, v in model.model_dump().items() if k in body.changes}
    if "template" in values:
        values["template"] = wire(values["template"])
    result = await update(ctx, "recurring_transactions", id, values, expected_version=body.expected_version)
    await audit(ctx, "UPDATE", "recurring_transactions", result, old)
    return wire(result)


@router.post("/goals/{id}/contributions", status_code=201)
async def contribute(id: UUID, body: Contribution, ctx: Ctx, idempotency_key: str = Header()):
    async def execute():
        goal = await get(ctx, "goals", id)
        require(goal["status"] == "ACTIVE", "Meta não está ativa.")
        if body.transaction_id:
            await get(ctx, "transactions", body.transaction_id)
        balance = await ctx.conn.fetchval(
            "SELECT COALESCE(sum(CASE WHEN direction='ADD' THEN amount ELSE -amount END),0) FROM goal_contributions WHERE goal_id=$1",
            id,
        )
        require(body.direction == "ADD" or body.amount <= balance, "Retirada maior que o valor alocado.")
        result = await insert(ctx, "goal_contributions", body.model_dump() | {"goal_id": id})
        await audit(ctx, "CONTRIBUTE", "goal_contributions", result)
        return result

    return await idempotent(ctx, "goal:contribution:" + str(id), idempotency_key, body.model_dump(), execute)


@router.get("/goals/{id}/contributions")
async def contributions(id: UUID, ctx: Ctx):
    await get(ctx, "goals", id)
    return wire(
        {
            "data": [
                dict(r)
                for r in await ctx.conn.fetch(
                    "SELECT * FROM goal_contributions WHERE goal_id=$1 ORDER BY contribution_date", id
                )
            ]
        }
    )


@router.get("/calendar")
async def calendar(ctx: Ctx, from_: date | None = None, to: date | None = None):
    return wire(
        {
            "data": [
                dict(r)
                for r in await ctx.conn.fetch(
                    "SELECT * FROM transactions WHERE status='PLANNED' AND ($1::date IS NULL OR due_date>=$1) AND ($2::date IS NULL OR due_date<=$2) ORDER BY due_date",
                    from_,
                    to,
                )
            ]
        }
    )
