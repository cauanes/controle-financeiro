from uuid import uuid4

from test_core import account


async def say(client, text):
    res = await client.post(
        "/api/v1/conversations/messages", json={"text": text}, headers={"Idempotency-Key": str(uuid4())}
    )
    assert res.status_code == 200, res.text
    return res.json()


async def test_clarification_no_guess(client):
    await account(client, "Nubank")
    await client.post("/api/v1/cards", json={"name": "Nubank", "closing_day": 20, "due_day": 28})
    r = await say(client, "Gastei 270 no mercado")
    assert r["status"] == "WAITING_INFORMATION"
    assert (await client.get("/api/v1/transactions")).json()["data"] == []
    r = await say(client, "Nubank")
    assert r["status"] == "WAITING_INFORMATION"
    r = await say(client, "crédito")
    assert "hoje" in r["question"]
    r = await say(client, "sim")
    assert r["status"] == "CONFIRMED"
    txs = (await client.get("/api/v1/transactions")).json()["data"]
    assert len(txs) == 1 and txs[0]["credit_card_id"]
    await say(client, "sim")
    assert len((await client.get("/api/v1/transactions")).json()["data"]) == 1


async def test_words_and_amazon(client):
    await account(client, "Itaú")
    r = await say(client, "Coloca cento e vinte e oito reais de gasolina hoje no débito Itaú")
    assert r["status"] == "CONFIRMED", r
    tx = (await client.get("/api/v1/transactions")).json()["data"][0]
    assert tx["amount"] == "128.00"
    r = await say(client, "Gastei 240 na Amazon hoje no débito Itaú")
    assert r["status"] == "WAITING_INFORMATION" and "categoria" in r["question"]
    r = await say(client, "Livros")
    assert r["status"] == "CONFIRMED", r


async def test_new_intent_cancel_and_correction(client):
    await account(client, "Nubank")
    await account(client, "Itaú")
    await say(client, "Gastei 270 no mercado")
    r = await say(client, "Gastei 128 de gasolina hoje no débito Nubank")
    assert "trocar" in r["question"]
    assert (await client.get("/api/v1/transactions")).json()["data"] == []
    r = await say(client, "trocar")
    assert r["status"] == "CONFIRMED", r
    r = await say(client, "Aquele gasto de 128 não foi Nubank, foi Itaú")
    assert r["status"] == "WAITING_CONFIRMATION", r
    r = await say(client, "sim")
    assert r["status"] == "CONFIRMED"
    assert len((await client.get("/api/v1/transactions")).json()["data"]) == 1
