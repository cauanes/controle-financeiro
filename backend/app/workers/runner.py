import asyncio
import logging
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from uuid import UUID

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
from app.modules.resources import normalize

logger = logging.getLogger("finance.worker")


def merge_classified_transactions(existing_txs: list[dict], new_txs: list[dict]) -> list[dict]:
    merged = list(existing_txs)

    def comparable_description(value):
        words = normalize(value or "").split(maxsplit=1)
        return words[1] if len(words) == 2 and len(words[0]) <= 2 else " ".join(words)

    for new_t in new_txs:
        is_dup = False
        for ex_t in merged:
            same_amt = abs(float(ex_t.get("amount", 0)) - float(new_t.get("amount", 0))) < 0.001
            same_desc = SequenceMatcher(
                None,
                comparable_description(ex_t.get("description", "")),
                comparable_description(new_t.get("description", "")),
            ).ratio() >= 0.9
            same_date = ex_t.get("date") == new_t.get("date")
            same_inst = ex_t.get("installment_current") == new_t.get("installment_current")
            if same_amt and same_desc and same_date and same_inst:
                is_dup = True
                break
        if not is_dup:
            merged.append(new_t)
    return merged


async def mark_possible_duplicates(ctx, transactions: list[dict], card_id: str | None) -> list[dict]:
    if not card_id:
        return transactions
    prior = await ctx.conn.fetch(
        "SELECT description,amount,transaction_date FROM transactions "
        "WHERE credit_card_id=$1 AND status<>'VOIDED'", UUID(str(card_id)),
    )

    def merchant(text):
        return re.sub(r"\s*\(parcela \d+/\d+\)$", "", normalize(text or ""))

    for item in transactions:
        item["possible_duplicate"] = False
        if item.get("type") == "PAYMENT_OR_CREDIT" or not item.get("date"):
            continue
        for old in prior:
            if (str(old["transaction_date"]) == item["date"]
                and old["amount"] == Decimal(str(item["amount"]))
                and SequenceMatcher(None, merchant(old["description"]), merchant(item["description"])).ratio() >= 0.9):
                item["possible_duplicate"] = True
                break
    return transactions


def invoice_difference(summary: dict, transactions: list[dict]) -> Decimal | None:
    if summary.get("total_amount") is None:
        return None
    imported = sum(
        (Decimal(str(t["amount"])) for t in transactions if t.get("type") != "PAYMENT_OR_CREDIT"),
        Decimal("0.00"),
    )
    return imported - Decimal(str(summary["total_amount"]))


def invoice_summary_conflict(existing: dict, incoming: dict) -> bool:
    """Keep screenshots from different invoice cycles out of one proposal."""
    if existing.get("issuer") and incoming.get("issuer"):
        if normalize(existing["issuer"]) != normalize(incoming["issuer"]):
            return True
    for key in ("due_date", "closing_date"):
        if existing.get(key) and incoming.get(key) and existing[key] != incoming[key]:
            return True
    if existing.get("total_amount") and incoming.get("total_amount"):
        if abs(Decimal(str(existing["total_amount"])) - Decimal(str(incoming["total_amount"]))) > Decimal("0.01"):
            return True
    return False


def match_credit_card(cards: list, issuer_name: str, last4s: set[str]):
    candidates = [c for c in cards if any(last4 in c["name"] for last4 in last4s)]
    if not candidates and issuer_name:
        candidates = [
            c for c in cards if c["name"].casefold() == issuer_name.casefold()
            or (c["issuer"] and c["issuer"].casefold() == issuer_name.casefold())
        ]
    return (candidates[0] if len(candidates) == 1 else None, len(candidates) > 1)


def build_invoice_question_text(summary: dict, transactions: list[dict], card_name: str) -> str:
    issuer_title = summary.get("issuer") or card_name or "Fatura de Cartão"
    lines = [f"📄 *Fatura identificada: {issuer_title}*"]
    if summary.get("total_amount"):
        lines.append(f"💰 *Total da fatura:* R$ {float(summary['total_amount']):.2f}")
    if summary.get("due_date"):
        try:
            due_fmt = datetime.strptime(summary["due_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
            clos_fmt = (
                datetime.strptime(summary["closing_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
                if summary.get("closing_date")
                else "-"
            )
            lines.append(f"🗓️ *Vencimento:* {due_fmt} | *Fechamento:* {clos_fmt}")
        except Exception:
            pass
    if summary.get("available_limit") and summary.get("total_limit"):
        lines.append(
            f"💳 *Limite:* R$ {float(summary['available_limit']):.2f} disp. de R$ {float(summary['total_limit']):.2f}"
        )

    importable = [t for t in transactions if t.get("type") != "PAYMENT_OR_CREDIT"]
    excluded = len(transactions) - len(importable)
    lines.append(f"\n📊 *Despesas propostas ({len(importable)} itens):*")
    for i, t in enumerate(importable[:20], 1):
        dt_str = "Sem data"
        if t.get("date"):
            try:
                dt_str = datetime.strptime(t["date"], "%Y-%m-%d").strftime("%d/%m")
            except Exception:
                dt_str = str(t["date"])
        inst_str = (
            f" ({t['installment_current']}/{t['installment_total']})"
            if t.get("installment_total")
            else ""
        )
        lines.append(
            f"{i}. {dt_str} · {t['description']} · R$ {float(t['amount']):.2f}{inst_str} "
            f"· categoria sugerida: {t.get('category_name', 'Outros')}"
            + (" ⚠️ possível duplicata" if t.get("possible_duplicate") else "")
        )
    if len(importable) > 20:
        lines.append(f"... e mais {len(importable) - 20} despesas. Esta fatura excede o limite de revisão no grupo.")
    if excluded:
        lines.append(f"{excluded} pagamento(s) ou crédito(s) reconhecido(s) foram excluídos da importação de despesas.")

    difference = invoice_difference(summary, transactions)
    if difference is not None:
        if difference == 0:
            lines.append("✅ A soma das despesas propostas confere com o total da fatura.")
        else:
            lines.append(
                f"⚠️ A soma das despesas propostas difere R$ {abs(difference):.2f} do total da fatura. "
                "Pode haver item faltando ou crédito não associado a esta fatura."
            )

    lines.append(f"\n_Apenas os itens listados acima serão importados no cartão *{card_name}*._")
    lines.append("Confira valores, datas e categorias; OCR pode errar. Nenhuma imagem foi importada ainda.")
    lines.append("Use *corrigir 2 34,17*, *categoria 2 Supermercado*, *adicionar 01/08/2026 AMAZON 34,17* ou *remover 2*.")
    if any(t.get("possible_duplicate") for t in importable) or difference not in (None, 0):
        lines.append("Há divergência ou possível duplicata. Corrija, envie mais imagens ou responda *confirmar mesmo assim* após conferir.")
    else:
        lines.append("Responda *sim* para confirmar ou *cancelar*.")
    return "\n".join(lines)


def build_invoice_header_text(summary: dict, card_name: str, card_ready: bool = False) -> str:
    issuer_title = summary.get("issuer") or card_name or "Fatura de Cartão"
    lines = [f"📄 *Fatura identificada: {issuer_title}*"]
    if summary.get("total_amount"):
        lines.append(f"💰 *Total da fatura:* R$ {float(summary['total_amount']):.2f}")
    if summary.get("due_date"):
        try:
            due_fmt = datetime.strptime(summary["due_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
            clos_fmt = (
                datetime.strptime(summary["closing_date"], "%Y-%m-%d").strftime("%d/%m/%Y")
                if summary.get("closing_date")
                else "-"
            )
            lines.append(f"🗓️ *Vencimento:* {due_fmt} | *Fechamento:* {clos_fmt}")
        except Exception:
            pass
    if summary.get("available_limit") and summary.get("total_limit"):
        lines.append(
            f"💳 *Limite:* R$ {float(summary['available_limit']):.2f} disp. de R$ {float(summary['total_limit']):.2f}"
        )
    lines.append("\nAinda não importei nada. Envie mais imagens com os lançamentos.")
    if not card_ready and (not summary.get("due_date") or not summary.get("closing_date")):
        lines.append("Também preciso ver o vencimento e o fechamento da fatura.")
    if card_name == "Cartão de Crédito":
        lines.append("Diga qual cartão é, por exemplo: *cartão Sam's Club*.")
    return "\n".join(lines)


def invoice_ready(summary: dict, transactions: list[dict], card_id: str | None, card_name: str | None) -> bool:
    importable = [t for t in transactions if t.get("type") != "PAYMENT_OR_CREDIT"]
    return bool(
        importable and len(importable) <= 20
        and all(t.get("date") and t.get("amount") for t in importable)
        and summary.get("closing_date")
        and (card_id or (card_name and summary.get("due_date") and summary.get("closing_date")))
    )


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
            try:
                img_bytes, mime = await channel.media(integration["instance_key"], message["media"])
                ocr_text = extract_text_from_image(img_bytes, mime)
                del img_bytes
            except DomainError as exc:
                if exc.status >= 500:
                    raise
                async with system_context(pool, **scope) as ctx:
                    session = await get(ctx, "conversation_sessions", message["session_id"])
                    await update(ctx, "conversation_messages", message["id"], {"media": None})
                    await response(
                        ctx, session, message, None,
                        "Não consegui ler esta imagem: " + exc.message + " Nenhum item foi importado. "
                        "Envie uma foto ou print JPG, PNG ou WebP legível.",
                    )
                    await event_done(ctx, event)
                return

            async with system_context(pool, **scope) as ctx:
                current = await get(ctx, "conversation_messages", message["id"])
                if current["processing_status"] in ("READY", "PROCESSED", "FAILED"):
                    await event_done(ctx, event)
                    return

                session = await get(ctx, "conversation_sessions", message["session_id"])
                ctx.user_id = session["user_id"]
                ctx.origin = "WHATSAPP" if session["channel"] == "WHATSAPP" else "CONVERSATION"
                if not ocr_text.strip():
                    await update(ctx, "conversation_messages", message["id"], {"media": None})
                    await response(
                        ctx,
                        session,
                        message,
                        None,
                        "Não consegui identificar texto legível nesta imagem. Envie uma foto mais nítida da fatura ou comprovante.",
                    )
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
                    tx_dict["category_source"] = cat_info["source"]
                    tx_dict["category_confidence"] = cat_info["confidence"]
                    if tx.card:
                        tx_dict["card"] = asdict(tx.card)
                    classified_txs.append(tx_dict)

                # Look for matching card in DB
                cards = await ctx.conn.fetch("SELECT * FROM credit_cards WHERE archived_at IS NULL")
                issuer_name = invoice.summary.issuer or ""
                last4s = {tx.card.last4 for tx in invoice.transactions if tx.card and tx.card.last4}
                matched_card, needs_card_choice = match_credit_card(cards, issuer_name, last4s)
                card_name = matched_card["name"] if matched_card else (
                    "Cartão de Crédito" if needs_card_choice else (issuer_name or "Cartão de Crédito")
                )
                has_summary_data = bool(
                    invoice.summary.total_amount
                    or invoice.summary.due_date
                    or invoice.summary.closing_date
                    or invoice.summary.issuer
                    or invoice.summary.total_limit
                )
                has_invoice_data = has_summary_data or len(classified_txs) > 0

                if has_invoice_data:
                    existing_action_row = await ctx.conn.fetchrow(
                        "SELECT * FROM pending_financial_actions WHERE session_id=$1 AND status IN ('WAITING_INFORMATION','WAITING_CONFIRMATION') FOR UPDATE",
                        session["id"],
                    )
                    existing_action = dict(existing_action_row) if existing_action_row else None
                    now = datetime.now(timezone.utc)
                    if existing_action and existing_action["expires_at"] <= now:
                        await update(ctx, "pending_financial_actions", existing_action["id"], {"status": "EXPIRED"})
                        existing_action = None

                    if existing_action and existing_action["intent"] != "IMPORT_INVOICE":
                        await update(ctx, "conversation_messages", message["id"], {
                            "normalized_text": ocr_text, "media": None,
                        })
                        await response(
                            ctx, session, message, existing_action,
                            "Li a imagem, mas não importei nada porque há outro lançamento pendente. "
                            "Responda à pergunta anterior ou envie *cancelar*; depois envie a fatura novamente.",
                        )
                        await event_done(ctx, event)
                        return

                    if existing_action and existing_action["intent"] == "IMPORT_INVOICE":
                        ex_data = existing_action.get("extracted_data") or {}
                        ex_txs = ex_data.get("transactions") or []
                        merged_txs = merge_classified_transactions(ex_txs, classified_txs)
                        ex_sum = ex_data.get("summary") or {}
                        new_sum = asdict(invoice.summary)
                        if invoice_summary_conflict(ex_sum, new_sum):
                            await update(ctx, "conversation_messages", message["id"], {
                                "normalized_text": ocr_text, "media": None,
                            })
                            await response(
                                ctx, session, message, existing_action,
                                "Esta imagem parece ser de outra fatura (emissor, total, vencimento ou fechamento diferente). "
                                "Não misturei os itens nem importei nada. Confirme ou cancele a proposta anterior "
                                "antes de enviar a outra fatura.",
                            )
                            await event_done(ctx, event)
                            return
                        merged_sum = {
                            "total_amount": new_sum.get("total_amount") or ex_sum.get("total_amount"),
                            "due_date": new_sum.get("due_date") or ex_sum.get("due_date"),
                            "closing_date": new_sum.get("closing_date") or ex_sum.get("closing_date"),
                            "minimum_payment": new_sum.get("minimum_payment") or ex_sum.get("minimum_payment"),
                            "available_limit": new_sum.get("available_limit") or ex_sum.get("available_limit"),
                            "total_limit": new_sum.get("total_limit") or ex_sum.get("total_limit"),
                            "issuer": new_sum.get("issuer") or ex_sum.get("issuer"),
                        }
                        final_card_id = str(matched_card["id"]) if matched_card else ex_data.get("matched_card_id")
                        merged_txs = await mark_possible_duplicates(ctx, merged_txs, final_card_id)
                        confirmed_card_name = ex_data.get("confirmed_card_name")
                        needs_card_choice = (ex_data.get("needs_card_choice") or needs_card_choice) and not (
                            confirmed_card_name or final_card_id
                        )
                        final_card_name = (
                            matched_card["name"]
                            if matched_card else (confirmed_card_name or (
                                "Cartão de Crédito" if needs_card_choice else
                                (ex_data.get("matched_card_name") or merged_sum.get("issuer") or "Cartão de Crédito")
                            ))
                        )
                        final_issuer = None if needs_card_choice else merged_sum.get("issuer")

                        if invoice_ready(merged_sum, merged_txs, final_card_id, confirmed_card_name or final_issuer):
                            question_text = build_invoice_question_text(merged_sum, merged_txs, final_card_name)
                            action_status = "WAITING_CONFIRMATION"
                        else:
                            question_text = build_invoice_header_text(merged_sum, final_card_name, bool(final_card_id))
                            action_status = "WAITING_INFORMATION"

                        raw_combined = ((existing_action.get("raw_message") or "") + "\n---\n" + ocr_text).strip()
                        action = await update(
                            ctx,
                            "pending_financial_actions",
                            existing_action["id"],
                            {
                                "raw_message": raw_combined,
                                "extracted_data": {
                                    "schema_version": 1,
                                    "summary": merged_sum,
                                    "transactions": merged_txs,
                                    "matched_card_id": final_card_id,
                                    "matched_card_name": final_card_name,
                                    "confirmed_card_name": confirmed_card_name,
                                    "issuer": final_issuer,
                                    "needs_card_choice": needs_card_choice,
                                },
                                "status": action_status,
                                "question": question_text,
                                "expires_at": now + timedelta(hours=24),
                                "confirmation_prompt_message_id": message["id"],
                            },
                        )
                        await response(ctx, session, message, action, question_text)
                    else:
                        new_sum = asdict(invoice.summary)
                        classified_txs = await mark_possible_duplicates(
                            ctx, classified_txs, str(matched_card["id"]) if matched_card else None
                        )
                        if invoice_ready(new_sum, classified_txs, str(matched_card["id"]) if matched_card else None,
                                         None if needs_card_choice else invoice.summary.issuer):
                            question_text = build_invoice_question_text(new_sum, classified_txs, card_name)
                            action_status = "WAITING_CONFIRMATION"
                        else:
                            question_text = build_invoice_header_text(new_sum, card_name, bool(matched_card))
                            action_status = "WAITING_INFORMATION"

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
                                    "summary": new_sum,
                                    "transactions": classified_txs,
                                    "matched_card_id": str(matched_card["id"]) if matched_card else None,
                                    "matched_card_name": card_name,
                                    "issuer": None if needs_card_choice else invoice.summary.issuer,
                                    "needs_card_choice": needs_card_choice,
                                },
                                "status": action_status,
                                "question": question_text,
                                "expires_at": now + timedelta(hours=24),
                                "confirmation_prompt_message_id": message["id"],
                            },
                        )
                        await response(ctx, session, message, action, question_text)
                    await update(ctx, "conversation_messages", message["id"], {"normalized_text": ocr_text, "media": None})
                else:
                    await update(ctx, "conversation_messages", message["id"], {"normalized_text": ocr_text, "media": None})
                    await response(
                        ctx, session, message, None,
                        "Li a imagem, mas não identifiquei lançamentos de fatura com segurança; nada foi importado. "
                        "Envie uma foto mais nítida ou escreva os dados por texto.",
                    )
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
