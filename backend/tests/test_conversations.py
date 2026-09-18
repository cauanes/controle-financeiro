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


async def test_installment_expenses(client):
    await client.post("/api/v1/cards", json={"name": "Nubank", "closing_day": 20, "due_day": 28})

    # Test 1: Total amount in X installments ("600 em 3x") with keyword category
    r = await say(client, "Gastei 600 em 3x no mercado no crédito Nubank hoje")
    assert r["status"] == "CONFIRMED", r
    assert "parcelada em 3x de R$ 200.00" in r["question"]
    assert "próximos 3 meses" in r["question"]

    txs = (await client.get("/api/v1/transactions")).json()["data"]
    assert len(txs) == 3
    group_id = txs[0]["installment_group_id"]
    assert group_id is not None
    assert all(t["installment_group_id"] == group_id for t in txs)
    assert sorted(t["installment_number"] for t in txs) == [1, 2, 3]
    assert all(t["installment_count"] == 3 for t in txs)
    assert all(t["amount"] == "200.00" for t in txs)
    # Check distinct invoices
    invoice_ids = {t["invoice_id"] for t in txs}
    assert len(invoice_ids) == 3

    # Test 2: Unit amount with multiplier ("10x de 150") without category, answering category
    r2 = await say(client, "Comprei 10x de 150 no cartão Nubank hoje")
    assert r2["status"] == "WAITING_INFORMATION" and "categoria" in r2["question"]
    r2_ans = await say(client, "Livros")
    assert r2_ans["status"] == "CONFIRMED", r2_ans
    assert "parcelada em 10x de R$ 150.00" in r2_ans["question"]

    all_txs = (await client.get("/api/v1/transactions")).json()["data"]
    assert len(all_txs) == 13
    new_txs = [t for t in all_txs if t["installment_count"] == 10]
    assert len(new_txs) == 10
    assert all(t["amount"] == "150.00" for t in new_txs)

    # Test 3: Word numbers ("duas vezes de 100 reais") with keyword
    r3 = await say(client, "Passei duas vezes de 100 reais de gasolina no crédito Nubank hoje")
    assert r3["status"] == "CONFIRMED", r3
    assert "parcelada em 2x de R$ 100.00" in r3["question"]


async def test_financial_indicators_and_currency_queries(client):
    r_currency = await say(client, "qual a cotação do dólar hoje?")
    assert r_currency["status"] == "ANSWERED"
    assert "Dólar" in r_currency["question"] or "Cotaç" in r_currency["question"] or "R$" in r_currency["question"]

    r_euro = await say(client, "câmbio do euro hoje")
    assert r_euro["status"] == "ANSWERED"
    assert "Euro" in r_euro["question"] or "Cotaç" in r_euro["question"] or "R$" in r_euro["question"]

    r_selic = await say(client, "qual a taxa selic e cdi hoje?")
    assert r_selic["status"] == "ANSWERED"
    assert "Selic" in r_selic["question"] or "CDI" in r_selic["question"] or "Indicadores" in r_selic["question"]


async def test_searxng_corporate_merchant_classification():
    from app.modules.categorization.merchant_classifier import classify_merchant

    class DummyCtx:
        conn = None

    ctx = DummyCtx()
    sendas = await classify_merchant(ctx, "SENDAS DISTRIBUIDORA S.A.")
    assert sendas["category_name"] == "Supermercado"
    assert sendas["source"] in ("local_searxng", "known_brand_rule")

    raizen = await classify_merchant(ctx, "RAIZEN COMBUSTIVEIS S.A.")
    assert raizen["category_name"] == "Combustível"

    cnpj_sendas = await classify_merchant(ctx, "06.057.223/0001-71")
    assert cnpj_sendas["category_name"] == "Supermercado"


