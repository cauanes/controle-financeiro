import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.db import emit, get, insert, make_pool, system_context, update
from app.core.errors import DomainError
from app.modules.categorization.merchant_classifier import classify_merchant
from app.modules.conversations.service import process, response
from app.modules.ingestion.audio import HttpTranscriptionProvider
from app.modules.ingestion.invoice_parser import parse_invoice
from app.modules.ingestion.ocr import extract_text_from_image
from app.modules.integrations.evolution import EvolutionAdapter

logger = logging.getLogger("finance.worker")


async def scopes(pool):
    async with pool.acquire() as conn:
        return [dict(row) for row in await conn.fetch("SELECT * FROM work_scopes()")]


async def event_done(ctx, event):
    await update(
        ctx, "outbox_events", event["id"], {"completed_at": datetime.now(timezone.utc), "last_error": None}
    )
    await insert(ctx, "processed_events", {"consumer": "main", "event_id": event["id"]})


async def claim(pool, scope):
    async with system_context(pool, **scope) as ctx:
        row = await ctx.conn.fetchrow(
            "SELECT * FROM outbox_events WHERE completed_at IS NULL AND available_at<=now() AND attempts<6 ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED"
        )
        if not row:
            return None
        return await update(
            ctx,
            "outbox_events",
            row["id"],
            {
                "attempts": row["attempts"] + 1,
                "available_at": datetime.now(timezone.utc) + timedelta(minutes=3),
            },
        )


async def handle(pool, scope, event, transcriber=None, channel=None):
    channel = channel or EvolutionAdapter()
    transcriber = transcriber or HttpTranscriptionProvider()
    kind = event["event_type"]
    if kind == "NormalizeMessage":
        async with system_context(pool, **scope) as ctx:
            message = await get(ctx, "conversation_messages", event["aggregate_id"])
            if message["processing_status"] in ("READY", "PROCESSED", "FAILED"):
                await event_done(ctx, event)
                return
            integration = await get(ctx, "integrations", message["integration_id"])
            require_active = integration["status"] == "ACTIVE"
            if not require_active:
                await update(
                    ctx,
                    "conversation_messages",
                    message["id"],
                    {"processing_status": "FAILED", "media": None},
                )
                await event_done(ctx, event)
                return
            if message["kind"] == "IMAGE":
                await update(ctx, "conversation_messages", message["id"], {"processing_status": "PROCESSING_OCR"})
            else:
                await update(ctx, "conversation_messages", message["id"], {"processing_status": "TRANSCRIBING"})

        if message["kind"] == "IMAGE":
            img_bytes, mime = await channel.media(integration["instance_key"], message["media"])
            ocr_text = extract_text_from_image(img_bytes, mime)
            del img_bytes

            async with system_context(pool, **scope) as ctx:
                current = await get(ctx, "conversation_messages", message["id"])
                if current["processing_status"] in ("READY", "PROCESSED", "FAILED"):
                    await event_done(ctx, event)
                    return

                invoice = parse_invoice(ocr_text)

                # Classify transactions
                classified_txs = []
                for tx in invoice.transactions:
                    cat_info = await classify_merchant(ctx, tx.description)
                    tx_dict = asdict(tx)
                    tx_dict["category_name"] = cat_info["category_name"]
                    tx_dict["category_id"] = cat_info.get("category_id")
                    if tx.card:
                        tx_dict["card"] = asdict(tx.card)
                    classified_txs.append(tx_dict)

                # Look for matching card in DB
                cards = await ctx.conn.fetch("SELECT * FROM credit_cards WHERE archived_at IS NULL")
                matched_card = None
                for c in cards:
                    c_name_l = c["name"].lower()
                    if invoice.summary.issuer and (c_name_l in invoice.summary.issuer.lower() or invoice.summary.issuer.lower() in c_name_l):
                        matched_card = c
                        break
                    for tx in invoice.transactions:
                        if tx.card and tx.card.last4 and tx.card.last4 in c_name_l:
                            matched_card = c
                            break
                if not matched_card and cards:
                    matched_card = cards[0]

                card_name = matched_card["name"] if matched_card else (invoice.summary.issuer or "Cartão de Crédito")
                has_invoice_data = bool(invoice.summary.total_amount or len(classified_txs) > 0 or invoice.summary.issuer)

                if has_invoice_data and len(classified_txs) > 0:
                    session = await get(ctx, "conversation_sessions", message["session_id"])
                    issuer_title = invoice.summary.issuer or "Fatura de Cartão"
                    lines = [f"📄 *Fatura identificada: {issuer_title}*"]
                    if invoice.summary.total_amount:
                        lines.append(f"💰 *Total da fatura:* R$ {invoice.summary.total_amount:.2f}")
                    if invoice.summary.due_date:
                        due_fmt = datetime.strptime(invoice.summary.due_date, "%Y-%m-%d").strftime("%d/%m/%Y")
                        clos_fmt = (
                            datetime.strptime(invoice.summary.closing_date, "%Y-%m-%d").strftime("%d/%m/%Y")
                            if invoice.summary.closing_date
                            else "-"
                        )
                        lines.append(f"🗓️ *Vencimento:* {due_fmt} | *Fechamento:* {clos_fmt}")
                    if invoice.summary.available_limit and invoice.summary.total_limit:
                        lines.append(
                            f"💳 *Limite:* R$ {invoice.summary.available_limit:.2f} disp. de R$ {invoice.summary.total_limit:.2f}"
                        )

                    lines.append(f"\n📊 *Lançamentos identificados ({len(classified_txs)} itens):*")
                    for i, t in enumerate(classified_txs[:10], 1):
                        dt_str = (
                            datetime.strptime(t["date"], "%Y-%m-%d").strftime("%d/%m")
                            if t.get("date")
                            else "Sem data"
                        )
                        inst_str = (
                            f" ({t['installment_current']}/{t['installment_total']})"
                            if t.get("installment_total")
                            else ""
                        )
                        lines.append(f"{i}. {dt_str} · {t['description']} · R$ {t['amount']:.2f}{inst_str} ➔ {t['category_name']}")
                    if len(classified_txs) > 10:
                        lines.append(f"... e mais {len(classified_txs) - 10} lançamentos.")

                    lines.append(f"\n_Deseja importar estes lançamentos no cartão *{card_name}*?_")
                    lines.append("Responda *sim* para confirmar ou *cancelar*.")
                    question_text = "\n".join(lines)

                    now = datetime.now(timezone.utc)
                    action = await insert(
                        ctx,
                        "pending_financial_actions",
                        {
                            "session_id": session["id"],
                            "user_id": session["user_id"],
                            "intent": "IMPORT_INVOICE",
                            "raw_message": ocr_text,
                            "extracted_data": {
                                "schema_version": 1,
                                "summary": asdict(invoice.summary),
                                "transactions": classified_txs,
                                "matched_card_id": str(matched_card["id"]) if matched_card else None,
                                "matched_card_name": card_name,
                                "issuer": invoice.summary.issuer,
                            },
                            "status": "WAITING_CONFIRMATION",
                            "question": question_text,
                            "expires_at": now + timedelta(hours=24),
                            "confirmation_prompt_message_id": message["id"],
                        },
                    )
                    await response(ctx, session, message, action, question_text)
                else:
                    await update(
                        ctx,
                        "conversation_messages",
                        message["id"],
                        {
                            "normalized_text": ocr_text,
                            "media": None,
                            "processing_status": "READY",
                        },
                    )
                    await emit(ctx, "ProcessMessage", message["id"])
                await event_done(ctx, event)
        else:
            audio, mime = await channel.media(integration["instance_key"], message["media"])
            transcription = await transcriber.transcribe(audio, mime)
            del audio
            async with system_context(pool, **scope) as ctx:
                current = await get(ctx, "conversation_messages", message["id"])
                if current["processing_status"] not in ("READY", "PROCESSED", "FAILED"):
                    await update(
                        ctx,
                        "conversation_messages",
                        message["id"],
                        {
                            "normalized_text": transcription.text,
                            "transcription_metadata": {
                                k: v for k, v in asdict(transcription).items() if k != "text"
                            },
                            "media": None,
                            "processing_status": "READY",
                        },
                    )
                    await emit(ctx, "ProcessMessage", message["id"])
                await event_done(ctx, event)
    elif kind == "SendMessage":
        async with system_context(pool, **scope) as ctx:
            outgoing = await get(ctx, "outgoing_messages", event["aggregate_id"])
            if outgoing["status"] in ("SENT", "FAILED", "UNKNOWN"):
                await event_done(ctx, event)
                return
            # A process crash after claiming the outbound call leaves delivery uncertain.
            if outgoing["status"] == "SENDING":
                await update(ctx, "outgoing_messages", outgoing["id"], {"status": "UNKNOWN"})
                await event_done(ctx, event)
                return
            identity = await get(ctx, "channel_identities", outgoing["recipient_identity_id"])
            integration = await get(ctx, "integrations", outgoing["integration_id"])
            recipient = identity["sender_key"]
            if outgoing["session_id"]:
                session = await get(ctx, "conversation_sessions", outgoing["session_id"])
                if session.get("whatsapp_group_id"):
                    group = await get(ctx, "whatsapp_groups", session["whatsapp_group_id"])
                    if group["status"] != "ACTIVE":
                        await update(ctx, "outgoing_messages", outgoing["id"], {"status": "FAILED"})
                        await event_done(ctx, event)
                        return
                    recipient = group["group_jid"]
            active = await ctx.conn.fetchval(
                "SELECT id FROM household_members WHERE user_id=$1 AND status='ACTIVE'", identity["user_id"]
            )
            if identity["revoked_at"] or integration["status"] != "ACTIVE" or not active:
                await update(ctx, "outgoing_messages", outgoing["id"], {"status": "FAILED"})
                await event_done(ctx, event)
                return
            # Alerts additionally recheck opt-in immediately before the send.
            rule_id = event["payload"].get("alert_rule_id")
            if rule_id:
                rule = await get(ctx, "alert_rules", rule_id)
                if not rule["enabled"] or not rule["opt_in"]:
                    await update(ctx, "outgoing_messages", outgoing["id"], {"status": "FAILED"})
                    await event_done(ctx, event)
                    return
            await update(
                ctx,
                "outgoing_messages",
                outgoing["id"],
                {"status": "SENDING", "attempts": outgoing["attempts"] + 1},
            )
        try:
            provider_id = await channel.send(integration["instance_key"], recipient, outgoing["text"])
        except (httpx.TimeoutException, httpx.NetworkError):
            async with system_context(pool, **scope) as ctx:
                await update(ctx, "outgoing_messages", outgoing["id"], {"status": "UNKNOWN"})
                await event_done(ctx, event)
            return
        except DomainError:
            async with system_context(pool, **scope) as ctx:
                await update(ctx, "outgoing_messages", outgoing["id"], {"status": "PENDING"})
            raise
        async with system_context(pool, **scope) as ctx:
            await update(
                ctx,
                "outgoing_messages",
                outgoing["id"],
                {"status": "SENT", "provider_message_id": provider_id, "sent_at": datetime.now(timezone.utc)},
            )
            await event_done(ctx, event)
    else:
        async with system_context(pool, **scope) as ctx:
            if await ctx.conn.fetchval(
                "SELECT id FROM processed_events WHERE event_id=$1 AND consumer=$2", event["id"], "main"
            ):
                return
            if kind == "ProcessMessage":
                message = await get(ctx, "conversation_messages", event["aggregate_id"])
                session = await get(ctx, "conversation_sessions", message["session_id"])
                await process(ctx, session, message)
            elif kind == "ImportConfirmed":
                from app.modules.ingestion.imports import execute_job

                await execute_job(ctx, event["aggregate_id"])
            elif kind.startswith("Transaction"):
                # Snapshots are marked stale and deterministically rebuilt on the next scheduled pass.
                await ctx.conn.execute(
                    "UPDATE financial_snapshots SET calculation_version='stale:'||id::text WHERE calculation_version NOT LIKE 'stale:%'"
                )
            await event_done(ctx, event)


async def tick(pool, transcriber=None, channel=None):
    count = 0
    for scope in await scopes(pool):
        event = await claim(pool, scope)
        if not event:
            continue
        try:
            await handle(pool, scope, event, transcriber, channel)
        except Exception as exc:
            # Store a code, never raw exception payload from a provider or financial message.
            code = exc.code if isinstance(exc, DomainError) else type(exc).__name__
            logger.warning(
                "event_failed event_id=%s code=%s attempt=%s", event["id"], code, event["attempts"]
            )
            async with system_context(pool, **scope) as ctx:
                attempts = event["attempts"] - 1 if code == "MESSAGE_NOT_READY" else event["attempts"]
                await update(
                    ctx,
                    "outbox_events",
                    event["id"],
                    {
                        "last_error": code,
                        "attempts": attempts,
                        "available_at": datetime.now(timezone.utc) + timedelta(seconds=min(60, 2**attempts)),
                    },
                )
                if attempts >= 6 and event["event_type"] in ("NormalizeMessage", "ProcessMessage"):
                    message = await get(ctx, "conversation_messages", event["aggregate_id"])
                    session = await get(ctx, "conversation_sessions", message["session_id"])
                    await response(
                        ctx,
                        session,
                        message,
                        None,
                        "Não consegui processar a mensagem. Envie novamente por texto.",
                    )
                    await update(
                        ctx,
                        "conversation_messages",
                        message["id"],
                        {"processing_status": "FAILED", "media": None},
                    )
        count += 1
    return count


async def run():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    pool = await make_pool()
    redis = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=2)
    try:
        iteration = 0
        while True:
            count = await tick(pool)
            iteration += 1
            if iteration % 30 == 0:
                from app.workers.scheduler import schedule

                await schedule(pool)
            if not count:
                # Redis wakes the worker; periodic SQL polling guarantees recovery if notifications are lost.
                try:
                    await redis.brpop("finance:wakeup", timeout=1)
                except (RedisError, OSError):
                    await asyncio.sleep(1)
    finally:
        await redis.aclose()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run())
