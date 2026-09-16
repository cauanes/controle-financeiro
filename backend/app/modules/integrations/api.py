import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import Field

from app.core.auth import Ctx
from app.core.config import settings
from app.core.db import Context, audit, digest, emit, get, insert, rows, set_scope, update, wire
from app.core.errors import require
from app.core.schemas import Strict, Version
from app.modules.conversations.service import ensure_session, receive
from app.modules.integrations.evolution import EvolutionAdapter

router = APIRouter(tags=["integrations"])


class Integration(Strict):
    instance_key: str = Field(min_length=1, max_length=100, pattern=r"^[\w.-]+$")
    provider: str = "EVOLUTION"


class GroupCreate(Strict):
    subject: str = Field(default="Cacau Finanças | Família", min_length=3, max_length=100)
    member_user_ids: list[UUID] = Field(min_length=1, max_length=30)


class GroupBind(Strict):
    group_jid: str = Field(pattern=r"^[0-9-]+@g\.us$")


@router.get("/api/v1/integrations")
async def listing(ctx: Ctx):
    ctx.write(admin=True)
    return wire(
        {
            "data": [
                {k: v for k, v in r.items() if k not in ("secret_ref", "config")}
                for r in await rows(ctx, "integrations")
                if r["provider"] != "INTERNAL"
            ]
        }
    )


@router.post("/api/v1/integrations", status_code=201)
async def creating(body: Integration, ctx: Ctx):
    ctx.write(admin=True)
    require(body.provider == "EVOLUTION", "Provider não suportado.")
    result = await insert(ctx, "integrations", body.model_dump())
    await audit(ctx, "CREATE", "integrations", result)
    return wire(result)


@router.post("/api/v1/integrations/{id}/link-token")
async def link_token(id: UUID, ctx: Ctx):
    integration = await get(ctx, "integrations", id)
    require(
        integration["provider"] == "EVOLUTION" and integration["status"] == "ACTIVE",
        "Integração não está ativa.",
    )
    token = secrets.token_urlsafe(18)
    await insert(
        ctx,
        "channel_link_tokens",
        {
            "integration_id": id,
            "user_id": ctx.user_id,
            "token_hash": digest(token),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
    )
    return {
        "code": token,
        "instruction": "Envie vincular " + token + " para o WhatsApp da integração.",
        "expires_in_seconds": 600,
    }


@router.post("/api/v1/integrations/{id}/disconnect")
async def disconnect(id: UUID, body: Version, ctx: Ctx):
    ctx.write(admin=True)
    result = await update(
        ctx, "integrations", id, {"status": "DISCONNECTED"}, expected_version=body.expected_version
    )
    await ctx.conn.execute("UPDATE channel_identities SET revoked_at=now() WHERE integration_id=$1", id)
    await ctx.conn.execute(
        "UPDATE pending_financial_actions SET status='CANCELLED',version=version+1 WHERE session_id IN (SELECT id FROM conversation_sessions WHERE integration_id=$1) AND status IN ('WAITING_INFORMATION','WAITING_CONFIRMATION')",
        id,
    )
    await audit(ctx, "DISCONNECT", "integrations", result)
    return wire(result)


@router.post("/api/v1/integrations/{id}/test")
async def test_connection(id: UUID, ctx: Ctx):
    ctx.write(admin=True)
    integration = await get(ctx, "integrations", id)
    return await EvolutionAdapter().test(integration["instance_key"])


@router.get("/api/v1/integrations/{id}/groups")
async def groups(id: UUID, ctx: Ctx):
    await get(ctx, "integrations", id)
    return wire({"data": [g for g in await rows(ctx, "whatsapp_groups") if g["integration_id"] == id]})


async def bind_group(ctx, integration, group_info):
    group_jid = group_info.get("id")
    require(
        isinstance(group_jid, str) and group_jid.endswith("@g.us"), "Evolution não retornou um grupo válido."
    )
    existing = await ctx.conn.fetchrow(
        "SELECT * FROM whatsapp_groups WHERE integration_id=$1 AND group_jid=$2", integration["id"], group_jid
    )
    if existing:
        return dict(existing)
    result = await insert(
        ctx,
        "whatsapp_groups",
        {
            "integration_id": integration["id"],
            "group_jid": group_jid,
            "subject": group_info.get("subject") or "Cacau Finanças | Família",
            "created_by": ctx.user_id,
        },
    )
    await audit(ctx, "CREATE", "whatsapp_groups", result)
    return result


@router.post("/api/v1/integrations/{id}/groups", status_code=201)
async def create_group(id: UUID, body: GroupCreate, ctx: Ctx):
    ctx.write(admin=True)
    integration = await get(ctx, "integrations", id)
    require(
        integration["provider"] == "EVOLUTION" and integration["status"] == "ACTIVE", "Integração inativa."
    )
    require(len(set(body.member_user_ids)) == len(body.member_user_ids), "Membro repetido.")
    numbers = []
    for member_id in body.member_user_ids:
        member = await ctx.conn.fetchrow(
            "SELECT role FROM household_members WHERE user_id=$1 AND status='ACTIVE'", member_id
        )
        require(member and member["role"] != "VIEWER", "Todos devem ser membros ativos desta família.")
        identity = await ctx.conn.fetchrow(
            "SELECT sender_key FROM channel_identities WHERE integration_id=$1 AND user_id=$2 AND revoked_at IS NULL",
            id,
            member_id,
        )
        require(identity, "Cada participante precisa vincular seu número antes de criar o grupo.")
        numbers.append(identity["sender_key"].split("@")[0])
    description = (
        "Grupo privado para registrar e consultar as finanças da família com o Cacau. "
        "As mensagens são visíveis a todos os participantes. Confirme valores, datas e contas antes de registrar."
    )
    group_info = await EvolutionAdapter().create_group(
        integration["instance_key"], body.subject, numbers, description
    )
    return wire(await bind_group(ctx, integration, group_info))


@router.post("/api/v1/integrations/{id}/groups/bind", status_code=201)
async def bind_existing_group(id: UUID, body: GroupBind, ctx: Ctx):
    ctx.write(admin=True)
    integration = await get(ctx, "integrations", id)
    group_info = await EvolutionAdapter().group_info(integration["instance_key"], body.group_jid)
    require(group_info.get("id") == body.group_jid, "O grupo retornado não corresponde ao solicitado.")
    return wire(await bind_group(ctx, integration, group_info))


@router.post("/api/v1/integrations/{id}/sync")
async def sync(id: UUID, ctx: Ctx):
    await get(ctx, "integrations", id)
    require(False, "Conector financeiro não habilitado nesta versão.", "NOT_IMPLEMENTED", 501)


@router.post("/webhooks/financial-provider")
async def financial_provider():
    return Response(status_code=404)


@router.post("/webhooks/evolution")
async def webhook(request: Request):
    # Gateway must inject this secret; raw public Evolution payload fields never authenticate.
    supplied = request.headers.get("x-webhook-secret", "")
    require(
        settings.evolution_webhook_secret
        and hmac.compare_digest(supplied, settings.evolution_webhook_secret),
        "Webhook não autenticado.",
        "UNAUTHENTICATED",
        401,
    )
    data_bytes = await request.body()
    require(len(data_bytes) <= 1024 * 1024, "Envelope do webhook excede 1 MB.")
    try:
        event = json.loads(data_bytes)
    except ValueError:
        require(False, "JSON inválido.")
    require(isinstance(event, dict) and isinstance(event.get("instance"), str), "Envelope inválido.")
    if event.get("event") not in ("messages.upsert", "MESSAGES_UPSERT"):
        return Response(status_code=204)
    data = event.get("data", {})
    key = data.get("key", {})
    require(isinstance(key, dict) and isinstance(key.get("id"), str), "Identificador de mensagem ausente.")
    chat_jid = key.get("remoteJid", "")
    is_group = chat_jid.endswith("@g.us")
    if key.get("fromMe") or not (is_group or chat_jid.endswith("@s.whatsapp.net")):
        return Response(status_code=204)
    sender = (
        (key.get("participantAlt") or key.get("participant") or data.get("participant"))
        if is_group
        else chat_jid
    )
    if not isinstance(sender, str) or not sender.endswith("@s.whatsapp.net"):
        return Response(status_code=204)
    message = data.get("message", {})
    text = message.get("conversation") or message.get("extendedTextMessage", {}).get("text")
    audio = message.get("audioMessage")
    if not text and not audio:
        return Response(status_code=204)
    require(text is None or isinstance(text, str) and len(text) <= 8000, "Texto inválido.")
    async with request.app.state.pool.acquire() as conn, conn.transaction():
        integration = await conn.fetchval("SELECT integration_lookup($1)", event["instance"])
        require(integration, "Integração não encontrada.", "NOT_FOUND", 404)
        await set_scope(conn, integration["tenant_id"], integration["household_id"])
        house = await conn.fetchrow("SELECT * FROM households WHERE id=$1", UUID(integration["household_id"]))
        ctx = Context(
            conn,
            UUID(integration["tenant_id"]),
            UUID(integration["household_id"]),
            None,
            "MEMBER",
            house["timezone"],
            "WHATSAPP",
        )
        await ctx.lock()
        iid = UUID(integration["id"])
        event_key = chat_jid + ":" + sender + ":" + key["id"]
        if await conn.fetchval(
            "SELECT id FROM webhook_receipts WHERE integration_id=$1 AND provider_event_key=$2",
            iid,
            event_key,
        ):
            return Response(status_code=200)
        identity = await conn.fetchrow(
            "SELECT * FROM channel_identities WHERE integration_id=$1 AND sender_key=$2 AND revoked_at IS NULL",
            iid,
            sender,
        )
        if not is_group and not identity and text and text.startswith("vincular "):
            allowed = await conn.fetchval(
                "SELECT throttle_login($1)", "link:" + digest(event["instance"] + sender)
            )
            require(allowed, "Muitas tentativas de vinculação.", "RATE_LIMITED", 429)
            token = await conn.fetchrow(
                "SELECT * FROM channel_link_tokens WHERE integration_id=$1 AND token_hash=$2 AND used_at IS NULL AND expires_at>now() FOR UPDATE",
                iid,
                digest(text[9:].strip()),
            )
            require(token, "Código de vinculação inválido ou expirado.")
            member = await conn.fetchrow(
                "SELECT * FROM household_members WHERE user_id=$1 AND status='ACTIVE'", token["user_id"]
            )
            require(member and member["role"] != "VIEWER", "Associação não permite o canal.")
            identity = await insert(
                ctx,
                "channel_identities",
                {
                    "integration_id": iid,
                    "user_id": token["user_id"],
                    "channel": "WHATSAPP",
                    "sender_key": sender,
                },
            )
            await update(ctx, "channel_link_tokens", token["id"], {"used_at": datetime.now(timezone.utc)})
            await insert(
                ctx,
                "webhook_receipts",
                {
                    "integration_id": iid,
                    "provider_event_key": event_key,
                    "payload_hash": hashlib.sha256(data_bytes).hexdigest(),
                    "status": "LINKED",
                },
            )
            return {"status": "linked"}
        require(identity, "Remetente não vinculado.", "FORBIDDEN", 403)
        member = await conn.fetchrow(
            "SELECT role FROM household_members WHERE user_id=$1 AND status='ACTIVE'", identity["user_id"]
        )
        require(member and member["role"] != "VIEWER", "Associação revogada.", "FORBIDDEN", 403)
        ctx.user_id = identity["user_id"]
        ctx.role = member["role"]
        group = None
        if is_group:
            group = await conn.fetchrow(
                "SELECT * FROM whatsapp_groups WHERE integration_id=$1 AND group_jid=$2 AND status='ACTIVE'",
                iid,
                chat_jid,
            )
            if not group:
                return Response(status_code=204)
        session = await ensure_session(ctx, dict(identity), dict(group) if group else None)
        media = (
            {"key": key, "mime_type": audio.get("mimetype", "audio/ogg"), "duration": audio.get("seconds")}
            if audio
            else None
        )
        incoming = await receive(
            ctx, session, text, event_key, kind="AUDIO" if audio else "TEXT", media=media
        )
        await insert(
            ctx,
            "webhook_receipts",
            {
                "integration_id": iid,
                "provider_event_key": event_key,
                "payload_hash": hashlib.sha256(data_bytes).hexdigest(),
                "message_id": incoming["id"],
                "status": "RECEIVED",
            },
        )
        await emit(ctx, "NormalizeMessage" if audio else "ProcessMessage", incoming["id"])
    return Response(status_code=202)
