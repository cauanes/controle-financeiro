import asyncio
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from app.core.db import set_scope
from app.core.errors import DomainError
from app.core.money import installments, invoice_dates, money


def test_exact_money_and_calendar():
    assert installments("100.00", 3) == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]
    assert invoice_dates(date(2026, 2, 28), 31, 5) == (date(2026, 2, 28), date(2026, 3, 5))
    for value in ("NaN", "Infinity", "1.001", 1.1):
        with pytest.raises(DomainError):
            money(value)


async def account(client, name="Conta", opening="1000.00"):
    response = await client.post(
        "/api/v1/accounts",
        json={"name": name, "opening_balance": opening, "opening_balance_date": "2026-01-01"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def transaction(client, source, amount="100.00", kind="EXPENSE", key=None, **extra):
    body = {
        "type": kind,
        "amount": amount,
        "transaction_date": "2026-09-01",
        "description": "Teste",
        "financial_source": source,
        **extra,
    }
    return await client.post(
        "/api/v1/transactions", json=body, headers={"Idempotency-Key": key or str(uuid4())}
    )


async def test_auth_isolation_and_rls(client, family):
    await account(client)
    pool = family["pool"]
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM accounts") == 0
        async with conn.transaction():
            await set_scope(conn, UUID(family["tenant_id"]), uuid4())
            assert await conn.fetchval("SELECT count(*) FROM accounts") == 0
    forbidden = await client.get("/api/v1/accounts", headers={"X-Household-Id": str(uuid4())})
    assert forbidden.status_code == 404
    csrf = await client.post("/api/v1/accounts", json={}, headers={"X-CSRF-Token": "bad"})
    assert csrf.status_code == 403
    assert (await client.post("/api/v1/auth/logout")).status_code == 200
    assert (await client.get("/api/v1/accounts")).status_code == 401


async def test_concurrent_idempotency_and_transfer(client):
    a = await account(client, "A")
    b = await account(client, "B", "0.00")
    responses = await asyncio.gather(
        *(transaction(client, {"kind": "ACCOUNT", "id": a["id"]}, key="same") for _ in range(20))
    )
    assert all(r.status_code == 201 for r in responses), [(r.status_code, r.text) for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert (
        await transaction(
            client,
            {"kind": "ACCOUNT_TRANSFER", "source_id": a["id"], "destination_id": b["id"]},
            kind="TRANSFER",
            amount="50.00",
        )
    ).status_code == 201
    balances = (await client.get("/api/v1/accounts")).json()["data"]
    assert sum(Decimal(x["balance"]) for x in balances) == Decimal("900.00")
    changed = await transaction(client, {"kind": "ACCOUNT", "id": a["id"]}, amount="200.00", key="same")
    assert changed.status_code == 409


async def test_card_payment_no_double_expense(client):
    a = await account(client)
    card = (
        await client.post("/api/v1/cards", json={"name": "Nubank", "closing_day": 20, "due_day": 28})
    ).json()
    r = await transaction(client, {"kind": "CREDIT_CARD", "id": card["id"]}, amount="200.00")
    assert r.status_code == 201, r.text
    invoice_id = r.json()["transactions"][0]["invoice_id"]
    pay = {"account_id": a["id"], "amount": "200.00", "transaction_date": "2026-09-02"}
    results = await asyncio.gather(
        *(
            client.post(
                f"/api/v1/invoices/{invoice_id}/payments", json=pay, headers={"Idempotency-Key": str(uuid4())}
            )
            for _ in range(2)
        )
    )
    assert sorted(r.status_code for r in results) == [201, 422]
    assert (await client.get(f"/api/v1/invoices/{invoice_id}")).json()["balance"] == "0.00"
    assert (await client.get("/api/v1/accounts")).json()["data"][0]["balance"] == "800.00"
    txs = (await client.get("/api/v1/transactions")).json()["data"]
    assert sum(Decimal(t["amount"]) for t in txs if t["type"] == "EXPENSE") == Decimal("200.00")


async def test_version_and_void(client):
    a = await account(client)
    tx = (await transaction(client, {"kind": "ACCOUNT", "id": a["id"]})).json()["transactions"][0]
    r = await client.patch(
        "/api/v1/transactions/" + tx["id"], json={"expected_version": 1, "changes": {"amount": "80.00"}}
    )
    assert r.status_code == 200, r.text
    assert (
        await client.patch(
            "/api/v1/transactions/" + tx["id"], json={"expected_version": 1, "changes": {"amount": "70.00"}}
        )
    ).status_code == 409
    assert (
        await client.delete(
            "/api/v1/transactions/" + tx["id"], params={"expected_version": 2, "reason": "Duplicado"}
        )
    ).status_code == 200
    assert (await client.get("/api/v1/accounts")).json()["data"][0]["balance"] == "1000.00"
    assert len((await client.get("/api/v1/transactions/" + tx["id"] + "/audit")).json()["data"]) == 3
