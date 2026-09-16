from uuid import UUID, uuid4

import pytest
from test_core import account

from app.core.db import system_context
from app.modules.conversations.service import internal_session, process, receive


@pytest.mark.asyncio
async def test_uncertain_audio_needs_transcription_confirmation(client, family):
    await account(client, "Itaú")
    ids = {key: UUID(family[key]) for key in ("tenant_id", "household_id", "user_id")}
    async with system_context(family["pool"], **ids) as ctx:
        session = await internal_session(ctx)
        message = await receive(
            ctx,
            session,
            "Gastei 32 de gasolina hoje no débito Itaú",
            str(uuid4()),
            kind="AUDIO",
            metadata={"confidence": 0.42},
        )
        answer = await process(ctx, session, message)
        assert answer["status"] == "WAITING_INFORMATION"
        assert "Ouvi:" in answer["question"]
    assert (await client.get("/api/v1/transactions")).json()["data"] == []
    reply = await client.post(
        "/api/v1/conversations/messages",
        json={"text": "sim"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "CONFIRMED"
    assert len((await client.get("/api/v1/transactions")).json()["data"]) == 1
