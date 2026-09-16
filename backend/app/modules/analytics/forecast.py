from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from app.core.db import get, rows
from app.core.errors import require
from app.modules.analytics.service import ZERO, metadata
from app.modules.ledger.service import account_balances, invoice_balance
from app.modules.planning.service import next_occurrence


async def cashflow(ctx, start=None, end=None, account_id=None):
    today = ctx.today()
    start = start or today
    end = end or start + timedelta(days=90)
    require(start == today, "Projeção começa na data atual, usando o saldo conhecido.")
    require(start <= end and (end - start).days <= 365, "Horizonte de projeção inválido (máximo 365 dias).")
    if account_id:
        await get(ctx, "accounts", account_id)
    accounts = await account_balances(ctx)
    opening = sum((a["balance"] for a in accounts if not account_id or a["id"] == account_id), ZERO)
    txs = await rows(ctx, "transactions")
    events = []
    overdue = []

    def add(key, day, income, expense, label, source=None):
        if day > end:
            return
        original_day = day
        if day < start:
            overdue.append({"origin_id": key, "due_date": original_day, "description": label})
            day = start
        events.append(
            {
                "origin_id": key,
                "date": day,
                "income": income,
                "expenses": expense,
                "description": label,
                "source": source,
            }
        )

    invoices = await rows(ctx, "credit_card_invoices")
    # All card obligations come from each invoice, including planned card purchases, once.
    for invoice in invoices:
        card = await get(ctx, "credit_cards", invoice["credit_card_id"])
        planned_payments = [
            t
            for t in txs
            if t["invoice_id"] == invoice["id"]
            and t["subtype"] == "INVOICE_PAYMENT"
            and t["status"] == "PLANNED"
        ]
        payment_accounts = {t["account_id"] for t in planned_payments}
        payment_account = (
            next(iter(payment_accounts)) if len(payment_accounts) == 1 else card["default_payment_account_id"]
        )
        if account_id and payment_account != account_id:
            continue
        amount = await invoice_balance(ctx, invoice["id"])
        amount += sum(
            (
                t["amount"]
                for t in txs
                if t["invoice_id"] == invoice["id"] and t["type"] == "EXPENSE" and t["status"] == "PLANNED"
            ),
            ZERO,
        )
        if amount > 0:
            add(
                "invoice:" + str(invoice["id"]),
                invoice["due_date"],
                ZERO,
                amount,
                "Fatura " + card["name"],
                str(payment_account) if payment_account else None,
            )
    for t in txs:
        if t["status"] != "PLANNED" or t["invoice_id"]:
            continue
        income = ZERO
        expense = ZERO
        if t["type"] == "INCOME" and (not account_id or t["account_id"] == account_id):
            income = t["amount"]
        elif t["type"] == "EXPENSE" and (not account_id or t["account_id"] == account_id):
            expense = t["amount"]
        elif t["type"] == "TRANSFER" and account_id:
            if t["account_id"] == account_id:
                expense = t["amount"]
            if t["destination_account_id"] == account_id:
                income = t["amount"]
        if income or expense:
            add(
                "transaction:" + str(t["id"]),
                t["due_date"] or t["transaction_date"],
                income,
                expense,
                t["description"],
            )
    for rule in await rows(ctx, "recurring_transactions"):
        if not rule["enabled"]:
            continue
        day = rule["next_due_date"]
        count = 0
        while day <= end and (rule["end_date"] is None or day <= rule["end_date"]) and count < 366:
            exists = any(
                t["recurring_transaction_id"] == rule["id"] and t["occurrence_date"] == day for t in txs
            )
            if not exists:
                template = rule["template"]
                source = template["financial_source"]
                amount = Decimal(template["amount"])
                income = ZERO
                expense = ZERO
                when = day
                if source["kind"] == "CREDIT_CARD":
                    card = await get(ctx, "credit_cards", source["id"])
                    from app.core.money import invoice_dates

                    _, when = invoice_dates(day, card["closing_day"], card["due_day"])
                    if not account_id or card["default_payment_account_id"] == account_id:
                        expense = amount
                elif source["kind"] == "ACCOUNT":
                    if not account_id or str(account_id) == source["id"]:
                        if template["type"] == "INCOME":
                            income = amount
                        else:
                            expense = amount
                elif source["kind"] == "ACCOUNT_TRANSFER" and account_id:
                    if str(account_id) == source["source_id"]:
                        expense = amount
                    if str(account_id) == source["destination_id"]:
                        income = amount
                if income or expense:
                    add(
                        "recurring:" + str(rule["id"]) + ":" + day.isoformat(),
                        when,
                        income,
                        expense,
                        template["description"],
                    )
            day = next_occurrence(rule, day)
            count += 1
    buckets = defaultdict(lambda: {"income": ZERO, "expenses": ZERO})
    for e in events:
        buckets[e["date"]]["income"] += e["income"]
        buckets[e["date"]]["expenses"] += e["expenses"]
    daily = []
    balance = opening
    day = start
    while day <= end:
        bucket = buckets[day]
        balance += bucket["income"] - bucket["expenses"]
        daily.append({"date": day, **bucket, "balance": balance})
        day += timedelta(days=1)
    return (await metadata(ctx, start, end, "projected_cash")) | {
        "opening_balance": opening,
        "daily": daily,
        "events": events,
        "overdue": overdue,
        "assumptions": [
            "Compromissos vencidos em aberto são alocados ao primeiro dia.",
            "Faturas entram pelo saldo restante, sem repetir pagamentos previstos.",
            "Receitas e despesas previstas dependem de confirmação futura.",
            "Faturas sem conta de pagamento definida aparecem apenas no consolidado.",
        ],
    }


async def categories(ctx, month=None):
    from app.core.money import add_months
    from app.modules.planning.service import budget_detail

    start = date.fromisoformat((month or ctx.today().strftime("%Y-%m")) + "-01")
    end = add_months(start, 1) - timedelta(days=1)
    elapsed = max(0, min((ctx.today() - start).days + 1, end.day))
    result = []
    for budget in await rows(ctx, "budgets"):
        if budget["period_start"] != start or budget["period_end"] != end:
            continue
        detail = await budget_detail(ctx, budget["id"])
        for line in detail["categories"]:
            # Only expenses already observed as of today feed the linear scenario.
            actual = await ctx.conn.fetchval(
                """WITH RECURSIVE tree AS (SELECT id FROM categories WHERE id=$1 UNION ALL SELECT c.id FROM categories c JOIN tree ON c.parent_id=tree.id)
            SELECT COALESCE(sum(amount),0) FROM transactions WHERE category_id IN (SELECT id FROM tree) AND type='EXPENSE' AND status='POSTED' AND competence_date BETWEEN $2 AND $3""",
                line["category_id"],
                start,
                min(ctx.today(), end),
            )
            result.append(
                {
                    "category_id": line["category_id"],
                    "actual": actual,
                    "budget": line["amount"],
                    "projected": (actual / elapsed * end.day).quantize(Decimal(".01"))
                    if elapsed >= 7
                    else None,
                    "observed_days": elapsed,
                }
            )
    return {
        "month": start.strftime("%Y-%m"),
        "scenario": "linear_daily_rate",
        "assumption": "Ritmo diário uniforme; não inclui acréscimo separado de recorrências.",
        "data": result,
    }
