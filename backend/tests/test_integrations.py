import asyncio
from dataclasses import asdict
from uuid import UUID, uuid4

import pytest
from test_core import account

from app.core.config import settings
from app.core.db import system_context
from app.core.errors import DomainError
from app.modules.conversations.service import internal_session, process, receive
from app.modules.ingestion.audio import FakeTranscriptionProvider, decode_audio, validate_audio
from app.workers.runner import tick


def test_audio_limits_and_signature():
    with pytest.raises(DomainError):
        validate_audio(b"not audio", "audio/ogg")
    with pytest.raises(DomainError):
        validate_audio(b"OggSaaa", "audio/ogg", 301)
    with pytest.raises(DomainError):
        decode_audio("%%", "audio/ogg")


async def test_text_audio_parity(client, family):
    await account(client, "Itaú")
    text = "Gastei 128 de gasolina hoje no débito Itaú"
    result = await FakeTranscriptionProvider(text).transcribe(b"OggSfixture", "audio/ogg")
    async with system_context(
        family["pool"], UUID(family["tenant_id"]), UUID(family["household_id"]), UUID(family["user_id"])
    ) as ctx:
        session = await internal_session(ctx)
        audio = await receive(
            ctx,
            session,
            result.text,
            "audio:" + str(uuid4()),
            kind="AUDIO",
            metadata={k: v for k, v in asdict(result).items() if k != "text"},
        )
        audio_result = await process(ctx, session, audio)
        text_msg = await receive(ctx, session, text, "text:" + str(uuid4()))
        text_result = await process(ctx, session, text_msg)
        assert audio_result["status"] == text_result["status"] == "CONFIRMED"
        assert audio_result["question"] == text_result["question"]


async def test_webhook_retries_and_outbox(client, family, monkeypatch):
    monkeypatch.setattr(settings, "evolution_webhook_secret", "test-secret")
    await account(client, "Itaú")
    integration = (
        await client.post("/api/v1/integrations", json={"instance_key": "test-" + uuid4().hex})
    ).json()
    token = (await client.post("/api/v1/integrations/" + integration["id"] + "/link-token")).json()["code"]

    def event(text, id):
        return {
            "event": "messages.upsert",
            "instance": integration["instance_key"],
            "data": {
                "key": {"id": id, "remoteJid": "5511999999999@s.whatsapp.net", "fromMe": False},
                "message": {"conversation": text},
            },
        }

    assert (
        await client.post(
            "/webhooks/evolution",
            json=event("vincular " + token, "link"),
            headers={"X-Webhook-Secret": "bad"},
        )
    ).status_code == 401
    assert (
        await client.post(
            "/webhooks/evolution",
            json=event("vincular " + token, "link"),
            headers={"X-Webhook-Secret": "test-secret"},
        )
    ).status_code == 200
    payload = event("Gastei 128 de gasolina hoje no débito Itaú", "expense")
    responses = await asyncio.gather(
        *(
            client.post("/webhooks/evolution", json=payload, headers={"X-Webhook-Secret": "test-secret"})
            for _ in range(20)
        )
    )
    assert sorted(r.status_code for r in responses) == [200] * 19 + [202]
    assert (await client.get("/api/v1/transactions")).json()["data"] == []

    class Channel:
        async def send(self, *args):
            return "provider-result"

    for _ in range(12):
        await tick(family["pool"], channel=Channel())
    assert len((await client.get("/api/v1/transactions")).json()["data"]) == 1
