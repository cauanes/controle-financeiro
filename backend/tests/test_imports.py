from uuid import uuid4

from test_core import account, transaction

from app.modules.ingestion.imports import normalize_row, read_file
from app.workers.runner import tick


async def preview(client, account_id, data):
    upload = await client.post("/api/v1/imports", files={"file": ("statement.csv", data, "text/csv")})
    assert upload.status_code == 201, upload.text
    job = upload.json()
    result = await client.post(
        "/api/v1/imports/" + job["id"] + "/preview",
        json={
            "expected_version": job["version"],
            "account_id": account_id,
            "mapping": {
                "date": "data",
                "amount": "valor",
                "description": "descricao",
                "date_format": "%Y-%m-%d",
                "locale": "pt-BR",
                "sign_convention": "negative_expense",
            },
        },
    )
    assert result.status_code == 200, result.text
    return result.json(), (await client.get("/api/v1/imports/" + job["id"] + "/rows")).json()["data"]


async def test_preview_duplicate_legitimate_same_amount(client, family):
    a = await account(client)
    data = b"data;valor;descricao\n2026-09-01;-12,00;Compra\n2026-09-01;-12,00;Compra\n"
    job, lines = await preview(client, a["id"], data)
    assert (await client.get("/api/v1/transactions")).json()["data"] == []
    res = await client.post(
        "/api/v1/imports/" + job["id"] + "/confirm",
        json={
            "expected_version": job["version"],
            "decisions": [{"row_id": r["id"], "action": "IMPORT"} for r in lines],
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert res.status_code == 202, res.text
    for _ in range(10):
        await tick(family["pool"])
    assert len((await client.get("/api/v1/transactions")).json()["data"]) == 2
    job2, lines2 = await preview(client, a["id"], data)
    assert all(r["status"] == "DUPLICATE" for r in lines2)


async def test_reconcile_two_sources_one_expense(client):
    a = await account(client)
    tx = (
        await transaction(client, {"kind": "ACCOUNT", "id": a["id"]}, amount="287.40", description="Mercado")
    ).json()["transactions"][0]
    job, lines = await preview(
        client, a["id"], b"data;valor;descricao\n2026-09-02;-287,40;SUPERMERCADO CONDOR\n"
    )
    matches = (await client.get("/api/v1/reconciliation")).json()["data"]
    assert len(matches) == 1
    res = await client.post(
        "/api/v1/reconciliation/" + matches[0]["id"] + "/accept",
        json={"expected_version": tx["version"]},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert res.status_code == 200, res.text
    txs = (await client.get("/api/v1/transactions")).json()["data"]
    assert len(txs) == 1 and len(txs[0]["sources"]) == 2
    assert (await client.get("/api/v1/accounts")).json()["data"][0]["balance"] == "712.60"


def test_ofx_and_mapping():
    kind, records, headers = read_file(
        b"OFXHEADER:100\n<OFX><STMTTRN><DTPOSTED>20260901<TRNAMT>-12.50<MEMO>Mercado<FITID>abc</STMTTRN></OFX>",
        "bank.ofx",
    )
    assert kind == "OFX"
    result = normalize_row(
        records[0], {"date_format": "%Y%m%d", "locale": "en-US", "sign_convention": "negative_expense"}
    )
    assert result["amount"] == "12.50" and result["type"] == "EXPENSE"
