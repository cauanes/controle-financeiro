from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from app.core.db import rows
from app.core.errors import require
from app.modules.ledger.service import account_balances

ZERO = Decimal("0.00")
VERSION = "1.0"


def period(ctx, start=None, end=None):
    end = end or ctx.today()
    start = start or end.replace(day=1)
    require(start <= end and (end - start).days <= 3660, "Período inválido ou maior que dez anos.")
    return start, end


async def metadata(ctx, start, end, basis):
    pending = await ctx.conn.fetchval(
        "SELECT count(*) FROM pending_financial_actions WHERE status IN ('WAITING_INFORMATION','WAITING_CONFIRMATION') AND expires_at>now()"
    )
    imports = await ctx.conn.fetchval(
        "SELECT count(*) FROM import_jobs WHERE status NOT IN ('COMPLETED','CANCELLED')"
    )
    return {
        "currency": "BRL",
        "timezone": ctx.timezone,
        "basis": basis,
        "from": start,
        "to": end,
        "as_of": ctx.today(),
        "calculation_version": VERSION,
        "data_quality": {"pending_actions": pending, "unfinished_imports": imports},
    }


async def summary(ctx, start=None, end=None):
    start, end = period(ctx, start, end)
    txs = await rows(ctx, "transactions")
    included = [t for t in txs if t["status"] == "POSTED" and start <= t["competence_date"] <= end]
    income = sum((t["amount"] for t in included if t["type"] == "INCOME"), ZERO)
    expenses = sum((t["amount"] for t in included if t["type"] == "EXPENSE"), ZERO)
    # Balance/patrimony cards are current position, clearly separated from the selected performance period.
    balances = await account_balances(ctx)
    available = sum((a["balance"] for a in balances), ZERO)
    card_debt = sum(
        (
            t["amount"] if t["type"] == "EXPENSE" else -t["amount"]
            for t in txs
            if t["status"] == "POSTED" and t["invoice_id"] and t["transaction_date"] <= ctx.today()
        ),
        ZERO,
    )
    assets = sum(
        (
            a["valuation"]
            for a in await rows(ctx, "assets")
            if not a["archived_at"] and not a["linked_account_id"] and a["valuation_date"] <= ctx.today()
        ),
        ZERO,
    )
    liabilities = sum(
        (
            a["outstanding_amount"]
            for a in await rows(ctx, "liabilities")
            if not a["archived_at"] and not a["linked_credit_card_id"] and a["valuation_date"] <= ctx.today()
        ),
        ZERO,
    )
    return (await metadata(ctx, start, end, "competence")) | {
        "income": income,
        "expenses": expenses,
        "result": income - expenses,
        "saving_rate": ((income - expenses) / income * 100).quantize(Decimal(".01")) if income else None,
        "available": available,
        "net_worth": available + assets - card_debt - liabilities,
        "card_debt": card_debt,
        "independent_assets": assets,
        "independent_liabilities": liabilities,
        "accounts": balances,
    }


async def categories(ctx, start=None, end=None):
    start, end = period(ctx, start, end)
    cats = await rows(ctx, "categories")
    indexed = {c["id"]: c for c in cats}
    totals = defaultdict(lambda: ZERO)
    for t in await rows(ctx, "transactions"):
        if t["status"] == "POSTED" and t["type"] == "EXPENSE" and start <= t["competence_date"] <= end:
            totals[t["category_id"]] += t["amount"]
    direct = dict(totals)
    for id, amount in direct.items():
        parent = indexed[id]["parent_id"] if id in indexed else None
        visited = set()
        while parent and parent not in visited:
            visited.add(parent)
            totals[parent] += amount
            parent = indexed[parent]["parent_id"]
    return (await metadata(ctx, start, end, "competence")) | {
        "data": [
            {
                "id": c["id"],
                "parent_id": c["parent_id"],
                "name": c["name"],
                "amount": totals[c["id"]],
                "direct_amount": direct.get(c["id"], ZERO),
            }
            for c in cats
            if c["kind"] == "EXPENSE"
        ]
        + [
            {
                "id": None,
                "parent_id": None,
                "name": "Sem categoria",
                "amount": direct.get(None, ZERO),
                "direct_amount": direct.get(None, ZERO),
            }
        ]
    }


async def cashflow(ctx, start=None, end=None, account_id=None):
    start, end = period(ctx, start, end)
    initial = await account_balances(ctx, start - timedelta(days=1))
    balance = sum((a["balance"] for a in initial if not account_id or a["id"] == account_id), ZERO)
    flows = defaultdict(lambda: {"income": ZERO, "expenses": ZERO, "opening_adjustment": ZERO})
    for a in await rows(ctx, "accounts"):
        if start <= a["opening_balance_date"] <= end and (not account_id or a["id"] == account_id):
            flows[a["opening_balance_date"]]["opening_adjustment"] += a["opening_balance"]
    for t in await rows(ctx, "transactions"):
        if t["status"] != "POSTED" or not start <= t["transaction_date"] <= end:
            continue
        day = t["transaction_date"]
        if t["type"] == "INCOME" and (not account_id or t["account_id"] == account_id):
            flows[day]["income"] += t["amount"]
        elif t["type"] == "EXPENSE" and t["account_id"] and (not account_id or t["account_id"] == account_id):
            flows[day]["expenses"] += t["amount"]
        elif t["type"] == "TRANSFER":
            if t["subtype"] == "INVOICE_PAYMENT" and (not account_id or t["account_id"] == account_id):
                flows[day]["expenses"] += t["amount"]
            elif account_id:
                if t["account_id"] == account_id:
                    flows[day]["expenses"] += t["amount"]
                if t["destination_account_id"] == account_id:
                    flows[day]["income"] += t["amount"]
    daily = []
    day = start
    while day <= end:
        flow = flows[day]
        balance += flow["income"] - flow["expenses"] + flow["opening_adjustment"]
        daily.append({"date": day, **flow, "balance": balance})
        day += timedelta(days=1)
    return (await metadata(ctx, start, end, "cash")) | {
        "opening_balance": sum(
            (a["balance"] for a in initial if not account_id or a["id"] == account_id), ZERO
        ),
        "data": daily,
    }


async def health(ctx, start=None, end=None):
    start, end = period(ctx, start, end)
    result = await summary(ctx, start, end)
    cash = await cashflow(ctx, start, end)
    reserve_accounts = [a for a in result["accounts"] if a["is_emergency_reserve"]]
    reserve = sum((a["balance"] for a in reserve_accounts), ZERO) if reserve_accounts else None
    from app.core.money import add_months

    month_start = ctx.today().replace(day=1)
    first = add_months(month_start, -3)
    essentials = {c["id"] for c in await rows(ctx, "categories") if c["is_essential"] is True}
    observed = [
        t
        for t in await rows(ctx, "transactions")
        if t["status"] == "POSTED"
        and first <= t["competence_date"] < month_start
        and t["category_id"] in essentials
        and t["type"] == "EXPENSE"
    ]
    months = {(t["competence_date"].year, t["competence_date"].month) for t in observed}
    average = sum((t["amount"] for t in observed), ZERO) / 3 if len(months) == 3 else None
    return {
        "flow": {
            "income": result["income"],
            "expenses": result["expenses"],
            "saving_rate": result["saving_rate"],
            "free_cash_flow": sum((d["income"] - d["expenses"] for d in cash["data"]), ZERO),
        },
        "security": {
            "reserve": reserve,
            "essential_monthly_average": average,
            "runway_months": (reserve / average).quantize(Decimal(".01"))
            if reserve is not None and average
            else None,
        },
        "commitments": {"card_debt": result["card_debt"], "liabilities": result["independent_liabilities"]},
        "patrimony": {
            "net_worth": result["net_worth"],
            "available": result["available"],
            "independent_assets": result["independent_assets"],
        },
        "data_quality": result["data_quality"],
    }
