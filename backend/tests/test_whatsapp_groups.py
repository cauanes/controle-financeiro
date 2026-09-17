from uuid import uuid4

import pytest
from test_core import account

from app.core.config import settings
from app.modules.integrations.evolution import EvolutionAdapter
from app.workers.runner import tick


@pytest.mark.asyncio
async def test_group_creation_routes_participant_and_ignores_chatter(client, family, monkeypatch):
    monkeypatch.setattr(settings, "evolution_webhook_secret", "group-secret")
    await account(client, "Itaú")
    integration_response = await client.post(
        "/api/v1/integrations", json={"instance_key": "finance-" + uuid4().hex}
    )
    assert integration_response.status_code == 201
    integration = integration_response.json()
    token_response = await client.post(f"/api/v1/integrations/{integration['id']}/link-token")
    token = token_response.json()["code"]
    jid = "5511999999999@s.whatsapp.net"
    group_jid = "120363123456789012@g.us"

    def event(text, key, *, group=False, sender=jid):
        return {
            "event": "messages.upsert",
            "instance": integration["instance_key"],
            "data": {
                "key": {
                    "id": key,
                    "remoteJid": group_jid if group else sender,
                    "participant": sender if group else None,
                    "fromMe": False,
                },
                "message": {"conversation": text},
            },
        }

    headers = {"X-Webhook-Secret": "group-secret"}
    link = await client.post("/webhooks/evolution", json=event("vincular " + token, "link"), headers=headers)
    assert link.status_code == 200, link.text
    user_id = family["user_id"]

    async def fake_create(self, instance, subject, participants, description):
        assert participants == [jid.split("@")[0]]
        assert "visíveis" in description
        return {"id": group_jid, "subject": subject}

    monkeypatch.setattr(EvolutionAdapter, "create_group", fake_create)
    group = await client.post(
        f"/api/v1/integrations/{integration['id']}/groups",
        json={"member_user_ids": [user_id]},
    )
    assert group.status_code == 201, group.text
    assert group.json()["group_jid"] == group_jid
    assert (
        await client.post(
            "/webhooks/evolution", json=event("Conversa da família", "chatter", group=True), headers=headers
        )
    ).status_code == 202
    assert (
        await client.post(
            "/webhooks/evolution",
            json=event("Gastei 32 de gasolina hoje no débito Itaú", "expense", group=True),
            headers=headers,
        )
    ).status_code == 202
    destinations = []

    class Channel:
        async def send(self, instance, recipient, text):
            destinations.append((recipient, text))
            return "outbound-id"

        async def media(self, instance, message):
            assert "imageMessage" in message["message"]
            return b"image-bytes", "image/jpeg"

    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    transactions = (await client.get("/api/v1/transactions")).json()["data"]
    assert len(transactions) == 1
    assert [destination for destination, _ in destinations] == [group_jid, group_jid]
    assert "Não entendi o pedido" in destinations[0][1]
    assert (await client.get("/api/v1/conversations")).json()["data"][0]["whatsapp_group_id"] == group.json()[
        "id"
    ]

    async def owner_jid(self, instance):
        return jid

    monkeypatch.setattr(EvolutionAdapter, "owner_jid", owner_jid)
    own_message = event("quanto gastei este mês?", "own-query", group=True)
    own_message["data"]["key"].update({"fromMe": True, "participant": "12345@lid"})
    assert (await client.post("/webhooks/evolution", json=own_message, headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert [destination for destination, _ in destinations] == [group_jid] * 3

    bot_echo = event(destinations[-1][1], "outbound-id", group=True)
    bot_echo["data"]["key"].update({"fromMe": True, "participant": "12345@lid"})
    assert (await client.post("/webhooks/evolution", json=bot_echo, headers=headers)).status_code == 204

    async def participant_jid(self, instance, group_jid, lid):
        assert group_jid == group.json()["group_jid"] and lid == "12345@lid"
        return jid

    monkeypatch.setattr(EvolutionAdapter, "participant_jid", participant_jid)
    linked_lid = event("quanto gastei este mês?", "lid-query", group=True)
    linked_lid["data"]["key"]["participant"] = "12345@lid"
    assert (await client.post("/webhooks/evolution", json=linked_lid, headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert [destination for destination, _ in destinations] == [group_jid] * 4

    income = event("Recebi 100 de salário no Itaú", "income-choice", group=True)
    assert (await client.post("/webhooks/evolution", json=income, headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "1. Minha família" in destinations[-1][1]

    button = event("", "button-choice", group=True)
    button["data"]["message"] = {"buttonsResponseMessage": {"selectedButtonId": "1"}}
    assert (await client.post("/webhooks/evolution", json=button, headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "Confirma esta receita?" in destinations[-1][1]

    invoice_text = (
        "Fatura\nValor atual\nR$ 72,31\nVence em 12/10/2026\nFecha em 01/10/2026\n"
        "Segunda-feira, 15 de junho\nPagamento recebido R$ 10,00\nCRF 4857 BGS SAMS CLUB BA R$ 72,31"
    )
    monkeypatch.setattr("app.workers.runner.extract_text_from_image", lambda image, mime: invoice_text)
    photo = event("", "image-with-pending-income", group=True)
    photo["data"]["message"] = {"imageMessage": {"mimetype": "image/jpeg"}}
    assert (await client.post("/webhooks/evolution", json=photo, headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "outro lançamento pendente" in destinations[-1][1]
    assert len((await client.get("/api/v1/transactions")).json()["data"]) == 1

    assert (await client.post("/webhooks/evolution", json=event("cancelar", "cancel-income", group=True), headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    photo["data"]["key"]["id"] = "image-invoice"
    photo["data"]["message"] = {"ephemeralMessage": {"message": photo["data"]["message"]}}
    assert (await client.post("/webhooks/evolution", json=photo, headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "Ainda não importei nada" in destinations[-1][1]

    assert (await client.post("/webhooks/evolution", json=event("cartão Sam's Club", "card-name", group=True), headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "72.31" in destinations[-1][1]
    assert "1 pagamento(s) ou crédito(s)" in destinations[-1][1]
    assert "soma das despesas propostas confere" in destinations[-1][1]
    assert "Responda *sim*" in destinations[-1][1]

    assert (await client.post("/webhooks/evolution", json=event("corrigir 1 73,31", "fix-amount", group=True), headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "Valor corrigido" in destinations[-1][1]
    assert "73.31" in destinations[-1][1]
    assert (await client.post("/webhooks/evolution", json=event("categoria 1 Alimentação", "fix-category", group=True), headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "Categoria corrigida" in destinations[-1][1]
    assert "categoria sugerida: Alimentação" in destinations[-1][1]

    assert (await client.post("/webhooks/evolution", json=event("sim", "confirm-invoice", group=True), headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "Não importei: a soma diverge" in destinations[-1][1]
    assert len((await client.get("/api/v1/transactions")).json()["data"]) == 1

    assert (await client.post("/webhooks/evolution", json=event("confirmar mesmo assim", "confirm-exception", group=True), headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "1 lançamentos" in destinations[-1][1]
    imported = (await client.get("/api/v1/transactions")).json()["data"]
    assert len(imported) == 2
    charge = next(item for item in imported if item["amount"] == "73.31")
    assert charge["transaction_date"] == "2026-06-15"
    invoice = (await client.get("/api/v1/invoices/" + charge["invoice_id"])).json()
    assert invoice["closing_date"] == "2026-10-01"

    monkeypatch.setattr("app.workers.runner.extract_text_from_image", lambda image, mime: "")
    photo["data"]["key"]["id"] = "unreadable-image"
    assert (await client.post("/webhooks/evolution", json=photo, headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "Não consegui identificar texto legível" in destinations[-1][1]
    assert len((await client.get("/api/v1/transactions")).json()["data"]) == 2

    from app.core.errors import DomainError

    def invalid_image(image, mime):
        raise DomainError("Formato de imagem inválido.")

    monkeypatch.setattr("app.workers.runner.extract_text_from_image", invalid_image)
    photo["data"]["key"]["id"] = "invalid-image"
    assert (await client.post("/webhooks/evolution", json=photo, headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "Formato de imagem inválido" in destinations[-1][1]
    assert "Nenhum item foi importado" in destinations[-1][1]

    pdf = event("", "unsupported-pdf", group=True)
    pdf["data"]["message"] = {"documentMessage": {"mimetype": "application/pdf"}}
    assert (await client.post("/webhooks/evolution", json=pdf, headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "ainda não leio PDF" in destinations[-1][1]

    assert (await client.post("/webhooks/evolution", json=event("sim", "nothing-to-confirm", group=True), headers=headers)).status_code == 202
    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    assert "Não há importação ou lançamento aguardando confirmação" in destinations[-1][1]


@pytest.mark.asyncio
async def test_group_requires_verified_member(client, monkeypatch):
    integration = (
        await client.post("/api/v1/integrations", json={"instance_key": "no-identity-" + uuid4().hex})
    ).json()

    async def impossible(*args):
        raise AssertionError("Group API must not be called")

    monkeypatch.setattr(EvolutionAdapter, "create_group", impossible)
    user_id = (await client.get("/api/v1/auth/me")).json()["user_id"]
    response = await client.post(
        f"/api/v1/integrations/{integration['id']}/groups", json={"member_user_ids": [user_id]}
    )
    assert response.status_code == 422
