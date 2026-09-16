from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from test_core import account, transaction

from app.core.db import system_context
from app.modules.notifications.service import next_allowed
from app.modules.planning.service import materialize


async def test_financial_reference_fixture(client):
    a = await account(client)
    await transaction(client, {"kind": "ACCOUNT", "id": a["id"]}, amount="500.00", kind="INCOME")
    await transaction(client, {"kind": "ACCOUNT", "id": a["id"]}, amount="100.00")
    card = (
        await client.post("/api/v1/cards", json={"name": "Card", "closing_day": 20, "due_day": 28})
    ).json()
    tx = (await transaction(client, {"kind": "CREDIT_CARD", "id": card["id"]}, amount="200.00")).json()[
        "transactions"
    ][0]
    await client.post(
        "/api/v1/invoices/" + tx["invoice_id"] + "/payments",
        json={"account_id": a["id"], "amount": "200.00", "transaction_date": "2026-09-02"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    result = (await client.get("/api/v1/analytics/summary?from=2026-09-01&to=2026-09-30")).json()
    assert result["available"] == result["net_worth"] == "1200.00"
    assert result["result"] == "200.00" and result["saving_rate"] == "40.00"
    cash = (await client.get("/api/v1/analytics/cashflow?from=2026-09-01&to=2026-09-30")).json()
    assert sum(Decimal(d["expenses"]) for d in cash["data"]) == Decimal("300.00")
    asset = await client.post(
        "/api/v1/assets",
        json={
            "name": "Conta espelhada",
            "kind": "cash",
            "valuation": "1200.00",
            "valuation_date": "2026-09-01",
            "linked_account_id": a["id"],
        },
    )
    assert asset.status_code == 201, asset.text
    assert (await client.get("/api/v1/analytics/summary")).json()["net_worth"] == "1200.00"


async def test_recurring_budget_and_goal(client, family):
    a = await account(client)
    cats = (await client.get("/api/v1/categories")).json()["data"]
    cat = next(c for c in cats if c["name"] == "Supermercado")
    parent = next(c for c in cats if c["name"] == "Alimentação")
    bad = await client.post(
        "/api/v1/budgets",
        json={
            "name": "Mês",
            "period_start": "2026-09-01",
            "period_end": "2026-09-30",
            "categories": [
                {"category_id": cat["id"], "amount": "100.00"},
                {"category_id": parent["id"], "amount": "200.00"},
            ],
        },
    )
    assert bad.status_code == 422
    rule = await client.post(
        "/api/v1/recurring",
        json={
            "template": {
                "type": "EXPENSE",
                "amount": "50.00",
                "transaction_date": "2026-01-31",
                "description": "Recorrente",
                "financial_source": {"kind": "ACCOUNT", "id": a["id"]},
            },
            "start_date": "2026-01-31",
            "frequency": "MONTHLY",
        },
    )
    assert rule.status_code == 201, rule.text
    for _ in range(2):
        async with system_context(
            family["pool"], UUID(family["tenant_id"]), UUID(family["household_id"]), UUID(family["user_id"])
        ) as ctx:
            await materialize(ctx, date(2026, 3, 31))
    txs = (await client.get("/api/v1/transactions")).json()["data"]
    assert sorted(t["transaction_date"] for t in txs) == ["2026-01-31", "2026-02-28", "2026-03-31"]
    assert all(t["status"] == "PLANNED" for t in txs)
    assert (await client.get("/api/v1/accounts")).json()["data"][0]["balance"] == "1000.00"
    goal = (await client.post("/api/v1/goals", json={"name": "Reserva", "target_amount": "5000.00"})).json()
    res = await client.post(
        "/api/v1/goals/" + goal["id"] + "/contributions",
        json={"amount": "100.00", "contribution_date": "2026-09-01"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert res.status_code == 201
    assert len((await client.get("/api/v1/transactions")).json()["data"]) == 3


def test_quiet_hours():
    now = datetime(2026, 9, 17, 2, tzinfo=timezone.utc)  # 23:00 São Paulo
    assert next_allowed(now, {"start": 22, "end": 8}, "America/Sao_Paulo") == datetime(
        2026, 9, 17, 11, tzinfo=timezone.utc
    )
