from uuid import UUID

from fastapi import APIRouter, Header
from pydantic import Field

from app.core.auth import Ctx
from app.core.db import get, idempotent, rows, wire
from app.core.errors import require
from app.core.schemas import Strict, Version
from app.modules.conversations import service

router = APIRouter(prefix="/api/v1", tags=["conversations"])


class Message(Strict):
    text: str = Field(min_length=1, max_length=8000)
    expected_version: int | None = None


@router.post("/conversations/messages")
async def send(body: Message, ctx: Ctx, idempotency_key: str = Header()):
    async def execute():
        session = await service.internal_session(ctx)
        message = await service.receive(
            ctx, session, body.text, "web:" + str(ctx.user_id) + ":" + idempotency_key
        )
        return await service.process(ctx, session, message)

    return await idempotent(ctx, "conversation:message", idempotency_key, body.model_dump(), execute)


@router.get("/conversations")
async def conversations(ctx: Ctx):
    return wire(
        {"data": [s for s in await rows(ctx, "conversation_sessions") if s["user_id"] == ctx.user_id]}
    )


@router.get("/conversations/{id}/messages")
async def messages(id: UUID, ctx: Ctx):
    session = await get(ctx, "conversation_sessions", id)
    require(session["user_id"] == ctx.user_id, "Conversa não encontrada.", "NOT_FOUND", 404)
    return wire(
        {
            "data": [
                dict(r)
                for r in await ctx.conn.fetch(
                    "SELECT id,kind,normalized_text,response,processing_status,received_at,sequence FROM conversation_messages WHERE session_id=$1 ORDER BY sequence",
                    id,
                )
            ]
        }
    )


@router.get("/pending-actions")
async def pending(ctx: Ctx):
    return wire(
        {
            "data": [
                a
                for a in await rows(ctx, "pending_financial_actions")
                if a["user_id"] == ctx.user_id and a["status"] in service.ACTIVE
            ]
        }
    )


async def answer_action(id, body, ctx, key):
    action = await get(ctx, "pending_financial_actions", id)
    require(action["user_id"] == ctx.user_id, "Pendência não encontrada.", "NOT_FOUND", 404)
    require(
        body.expected_version == action["version"], "Proposta mudou. Recarregue.", "VERSION_CONFLICT", 409
    )
    require(action["status"] in service.ACTIVE, "Proposta encerrada.", "STATE_CONFLICT", 409)
    session = await get(ctx, "conversation_sessions", action["session_id"])
    message = await service.receive(ctx, session, body.text, "answer:" + key)
    return await service.process(ctx, session, message)


@router.post("/pending-actions/{id}/answer")
async def answer(id: UUID, body: Message, ctx: Ctx, idempotency_key: str = Header()):
    return await idempotent(
        ctx,
        "pending:answer:" + str(id),
        idempotency_key,
        body.model_dump(),
        lambda: answer_action(id, body, ctx, idempotency_key),
    )


@router.post("/pending-actions/{id}/confirm")
async def confirm(id: UUID, body: Version, ctx: Ctx, idempotency_key: str = Header()):
    return await answer(id, Message(text="sim", expected_version=body.expected_version), ctx, idempotency_key)


@router.post("/pending-actions/{id}/cancel")
async def cancel(id: UUID, body: Version, ctx: Ctx, idempotency_key: str = Header()):
    return await answer(
        id, Message(text="cancelar", expected_version=body.expected_version), ctx, idempotency_key
    )
