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
            destinations.append(recipient)
            return "outbound-id"

    for _ in range(16):
        await tick(family["pool"], channel=Channel())
    transactions = (await client.get("/api/v1/transactions")).json()["data"]
    assert len(transactions) == 1
    assert destinations == [group_jid]
    assert (await client.get("/api/v1/conversations")).json()["data"][0]["whatsapp_group_id"] == group.json()[
        "id"
    ]


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
