from datetime import timedelta

from app.core.db import audit, get, insert, rows, update, wire
from app.core.errors import require
from app.core.money import add_months
from app.core.schemas import Budget, Recurring, Transaction
from app.modules.ledger.service import create, validate


async def validate_budget(ctx, body, exclude=None):
    require(body.period_end >= body.period_start, "Período de orçamento inválido.")
    overlap = await ctx.conn.fetchval(
        "SELECT id FROM budgets WHERE period_start<=$1 AND period_end>=$2 AND ($3::uuid IS NULL OR id<>$3) LIMIT 1",
        body.period_end,
        body.period_start,
        exclude,
    )
    require(not overlap, "Já existe orçamento neste período.")
    selected = {line.category_id for line in body.categories}
    require(len(selected) == len(body.categories), "Categoria repetida no orçamento.")
    for line in body.categories:
        require(line.amount >= 0, "Orçamento não pode ser negativo.")
        category = await get(ctx, "categories", line.category_id)
        require(
            category["kind"] == "EXPENSE" and not category["archived_at"], "Categoria de orçamento inválida."
        )
        while category["parent_id"]:
            require(
                category["parent_id"] not in selected, "Não inclua categoria pai e filha no mesmo orçamento."
            )
            category = await get(ctx, "categories", category["parent_id"])


async def create_budget(ctx, body: Budget):
    await validate_budget(ctx, body)
    result = await insert(ctx, "budgets", body.model_dump(exclude={"categories"}))
    for line in body.categories:
        await insert(ctx, "budget_categories", {"budget_id": result["id"], **line.model_dump()})
    await audit(
        ctx,
        "CREATE",
        "budgets",
        result | {"categories": wire([line.model_dump() for line in body.categories])},
    )
    return result


async def budget_detail(ctx, id):
    budget = await get(ctx, "budgets", id)
    lines = []
    for row in await ctx.conn.fetch("SELECT * FROM budget_categories WHERE budget_id=$1", id):
        actual = await ctx.conn.fetchval(
            """WITH RECURSIVE tree AS (SELECT id FROM categories WHERE id=$1 UNION ALL SELECT c.id FROM categories c JOIN tree ON c.parent_id=tree.id)
        SELECT COALESCE(sum(amount),0) FROM transactions WHERE category_id IN (SELECT id FROM tree) AND type='EXPENSE' AND status='POSTED' AND competence_date BETWEEN $2 AND $3""",
            row["category_id"],
            budget["period_start"],
            budget["period_end"],
        )
        lines.append(dict(row) | {"actual": actual, "remaining": row["amount"] - actual})
    return budget | {"categories": lines}


async def create_recurring(ctx, body: Recurring):
    require(body.end_date is None or body.end_date >= body.start_date, "Fim anterior ao início.")
    require(body.template.installment_count == 1, "Recorrência parcelada não suportada.")
    await validate(ctx, body.template)
    result = await insert(
        ctx,
        "recurring_transactions",
        body.model_dump(exclude={"template"})
        | {
            "template": wire(body.template.model_dump()),
            "next_due_date": body.start_date,
            "created_by": ctx.user_id,
        },
    )
    await audit(ctx, "CREATE", "recurring_transactions", result)
    return result


def next_occurrence(rule, day):
    if rule["frequency"] == "WEEKLY":
        return day + timedelta(weeks=rule["interval_count"])
    return add_months(
        day, rule["interval_count"] * (12 if rule["frequency"] == "YEARLY" else 1), rule["start_date"].day
    )


async def materialize(ctx, horizon):
    for rule in await rows(ctx, "recurring_transactions"):
        if not rule["enabled"]:
            continue
        day = rule["next_due_date"]
        count = 0
        user_id = rule["created_by"]
        member = await ctx.conn.fetchrow(
            "SELECT role FROM household_members WHERE user_id=$1 AND status='ACTIVE'", user_id
        )
        if not member or member["role"] == "VIEWER":
            continue
        old_user, old_role = ctx.user_id, ctx.role
        ctx.user_id, ctx.role = user_id, member["role"]
        try:
            while day <= horizon and (rule["end_date"] is None or day <= rule["end_date"]) and count < 120:
                exists = await ctx.conn.fetchval(
                    "SELECT id FROM transactions WHERE recurring_transaction_id=$1 AND occurrence_date=$2",
                    rule["id"],
                    day,
                )
                if not exists:
                    body = Transaction.model_validate(
                        rule["template"]
                        | {
                            "status": "PLANNED",
                            "transaction_date": day.isoformat(),
                            "competence_date": day.isoformat(),
                            "due_date": day.isoformat(),
                        }
                    )
                    await create(
                        ctx,
                        body,
                        source_key="recurring:" + str(rule["id"]) + ":" + day.isoformat(),
                        recurring_id=rule["id"],
                        occurrence_date=day,
                    )
                day = next_occurrence(rule, day)
                count += 1
            await update(ctx, "recurring_transactions", rule["id"], {"next_due_date": day})
        finally:
            ctx.user_id, ctx.role = old_user, old_role
