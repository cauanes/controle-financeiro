import re
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from app.core.db import audit, emit, get, insert, rows, update, wire
from app.core.errors import DomainError, require
from app.core.schemas import Transaction
from app.modules.conversations.parser import RuleParser, amounts, evidence, intent
from app.modules.ledger import service as ledger
from app.modules.resources import normalize

ACTIVE = ("WAITING_INFORMATION", "WAITING_CONFIRMATION")
parser = RuleParser()


async def internal_session(ctx):
    integration = await ctx.conn.fetchrow("SELECT * FROM integrations WHERE provider='INTERNAL'")
    if not integration:
        integration = await insert(
            ctx, "integrations", {"provider": "INTERNAL", "instance_key": "internal:" + str(ctx.household_id)}
        )
    identity = await ctx.conn.fetchrow(
        "SELECT * FROM channel_identities WHERE integration_id=$1 AND user_id=$2 AND revoked_at IS NULL",
        integration["id"],
        ctx.user_id,
    )
    if not identity:
        identity = await insert(
            ctx,
            "channel_identities",
            {
                "integration_id": integration["id"],
                "user_id": ctx.user_id,
                "channel": "INTERNAL",
                "sender_key": str(ctx.user_id),
            },
        )
    return await ensure_session(ctx, dict(identity))


async def ensure_session(ctx, identity, group=None):
    session = await ctx.conn.fetchrow(
        "SELECT * FROM conversation_sessions WHERE channel_identity_id=$1 AND whatsapp_group_id IS NOT DISTINCT FROM $2::uuid",
        identity["id"],
        group["id"] if group else None,
    )
    if session:
        return dict(session)
    return await insert(
        ctx,
        "conversation_sessions",
        {
            "integration_id": identity["integration_id"],
            "channel_identity_id": identity["id"],
            "user_id": identity["user_id"],
            "channel": identity["channel"],
            "whatsapp_group_id": group["id"] if group else None,
        },
    )


async def receive(
    ctx, session, text, message_key, *, kind="TEXT", received_at=None, metadata=None, media=None
):
    old = await ctx.conn.fetchrow(
        "SELECT * FROM conversation_messages WHERE integration_id=$1 AND provider_message_id=$2 AND direction='IN'",
        session["integration_id"],
        message_key,
    )
    if old:
        return dict(old)
    session = await get(ctx, "conversation_sessions", session["id"], lock=True)
    msg = await insert(
        ctx,
        "conversation_messages",
        {
            "session_id": session["id"],
            "integration_id": session["integration_id"],
            "provider_message_id": message_key,
            "sequence": session["next_sequence"],
            "kind": kind,
            "raw_text": text,
            "normalized_text": text,
            "transcription_metadata": metadata,
            "media": media,
            "processing_status": "RECEIVED" if (kind in ("AUDIO", "IMAGE") and (text is None or media is not None)) else "READY",
            "received_at": received_at or datetime.now(timezone.utc),
        },
    )
    await update(
        ctx,
        "conversation_sessions",
        session["id"],
        {"next_sequence": session["next_sequence"] + 1, "last_activity_at": datetime.now(timezone.utc)},
    )
    return msg


async def response(ctx, session, message, action, text, result=None):
    choices = action.get("extracted_data", {}).get("choice_options", []) if action and action["status"] in ACTIVE else []
    payload = {
        "action_id": str(action["id"]) if action else None,
        "status": action["status"] if action else "ANSWERED",
        "question": text,
        "execution_result": wire(result) if result else None,
        "version": action["version"] if action else None,
        "choices": [{"label": option["label"], "value": str(index)} for index, option in enumerate(choices, 1)],
    }
    await update(
        ctx,
        "conversation_messages",
        message["id"],
        {
            "processing_status": "PROCESSED",
            "processed_at": datetime.now(timezone.utc),
            "pending_action_id": action["id"] if action else None,
            "response": payload,
        },
    )
    if session["channel"] == "WHATSAPP":
        outgoing = await insert(
            ctx,
            "outgoing_messages",
            {
                "session_id": session["id"],
                "integration_id": session["integration_id"],
                "recipient_identity_id": session["channel_identity_id"],
                "client_message_id": uuid4(),
                "text": text,
            },
        )
        await emit(ctx, "SendMessage", outgoing["id"])
    return payload


async def complete(ctx, action):
    candidate = action["extracted_data"]
    if action["intent"] == "UPDATE_TRANSACTION":
        result = await ledger.patch(
            ctx, action["target_transaction_id"], candidate["changes"], action["target_version"]
        )
    elif action["intent"] == "DELETE_TRANSACTION":
        result = await ledger.void(
            ctx, action["target_transaction_id"], action["target_version"], "Exclusão confirmada na conversa"
        )
    elif action["intent"] == "CREATE_GOAL":
        from app.core.schemas import Goal

        goal = Goal.model_validate(candidate["goal"])
        result = await insert(ctx, "goals", goal.model_dump())
        await audit(ctx, "CREATE", "goals", result)
    elif action["intent"] == "CREATE_BUDGET":
        from app.core.schemas import Budget
        from app.modules.planning.service import create_budget

        result = await create_budget(ctx, Budget.model_validate(candidate["budget"]))
    elif action["intent"] == "IMPORT_INVOICE":
        summary_info = candidate.get("summary") or {}
        require(summary_info.get("closing_date"), "Não importei: falta o fechamento da fatura.")
        invoice_closing_date = date.fromisoformat(summary_info["closing_date"])
        card_id = candidate.get("matched_card_id")
        if card_id:
            card = await get(ctx, "credit_cards", card_id)
        else:
            card_name = candidate.get("confirmed_card_name") or candidate.get("issuer")
            require(
                card_name and summary_info.get("due_date") and summary_info.get("closing_date"),
                "Não importei: identifique o cartão e as datas de vencimento e fechamento.",
            )
            due_day = date.fromisoformat(summary_info["due_date"]).day
            closing_day = date.fromisoformat(summary_info["closing_date"]).day
            card = await insert(
                ctx,
                "credit_cards",
                {
                    "name": card_name,
                    "issuer": card_name,
                    "limit_amount": str(summary_info["total_limit"]) if summary_info.get("total_limit") else None,
                    "closing_day": closing_day,
                    "due_day": due_day,
                },
            )
            await audit(ctx, "CREATE", "credit_cards", card)
            card_id = str(card["id"])

        categories = {c["name"].lower(): c["id"] for c in await rows(ctx, "categories") if c["kind"] == "EXPENSE"}

        async def get_or_create_category(cat_name: str) -> UUID:
            cat_l = (cat_name or "Outros").lower()
            if cat_l in categories:
                return categories[cat_l]
            new_cat = await insert(
                ctx,
                "categories",
                {"name": cat_name or "Outros", "kind": "EXPENSE"},
            )
            await audit(ctx, "CREATE", "categories", new_cat)
            categories[cat_l] = new_cat["id"]
            return new_cat["id"]

        created_txs = []
        for idx, t in enumerate(candidate.get("transactions", [])):
            if t.get("type") == "PAYMENT_OR_CREDIT":
                continue
            require(t.get("date"), "Não importei: há lançamento sem data. Confira o resumo.")
            tx_date = date.fromisoformat(t["date"])

            cat_id = await get_or_create_category(t.get("category_name", "Outros"))
            installment_label = (
                f" (parcela {t['installment_current']}/{t['installment_total']})"
                if t.get("installment_current") and t.get("installment_total") else ""
            )
            tx_data = {
                "type": "EXPENSE",
                "amount": f"{t['amount']:.2f}",
                "description": t["description"] + installment_label,
                "transaction_date": tx_date.isoformat(),
                "financial_source": {
                    "kind": "CREDIT_CARD",
                    "id": card_id,
                },
                "category_id": str(cat_id),
                "installment_count": 1,
            }
            body = Transaction.model_validate(tx_data)
            created = await ledger.create(
                ctx,
                body,
                source_type="INVOICE_OCR",
                source_key=f"invoice:{action['id']}:{idx}",
                invoice_closing_date=invoice_closing_date,
            )
            created_txs.append(created)

        result = {
            "imported_count": len(created_txs),
            "card_id": str(card_id),
            "card_name": card["name"],
            "transactions": [str(c[0]["id"]) if isinstance(c, list) else str(c["id"]) for c in created_txs],
        }
    else:
        values = {k: v["value"] for k, v in candidate["fields"].items() if k in Transaction.model_fields}
        values["description"] = values.get("description", "Lançamento conversacional")
        body = Transaction.model_validate(values)
        result = await ledger.create(
            ctx,
            body,
            source_type="WHATSAPP" if ctx.origin == "WHATSAPP" else "CONVERSATION",
            source_key="action:" + str(action["id"]),
        )
    action = await update(
        ctx,
        "pending_financial_actions",
        action["id"],
        {"status": "CONFIRMED", "execution_result": wire(result), "question": None},
    )
    return action, result


def numbered_choices(action, text, choices):
    options = [
        {"id": f"choice:{action['id']}:{index}", "label": label, "reply": reply}
        for index, (label, reply) in enumerate(choices, 1)
    ]
    if options:
        text += "\n" + "\n".join(f"{index}. {option['label']}" for index, option in enumerate(options, 1))
        text += "\nResponda com o número ou escreva a opção."
    return text, options


async def ask(ctx, action, candidate, field, text, now, choices=None):
    candidate["answer_field"] = field
    text, candidate["choice_options"] = numbered_choices(action, text, choices or [])
    action = await update(
        ctx,
        "pending_financial_actions",
        action["id"],
        {
            "extracted_data": candidate,
            "missing_fields": [field] if field else [],
            "ambiguous_fields": candidate.get("ambiguous_fields", []),
            "status": "WAITING_INFORMATION",
            "question": text,
            "expires_at": min(now + timedelta(hours=24), action["created_at"] + timedelta(days=7)),
        },
    )
    return action, text


async def propose(ctx, action, candidate, text, message, now, choices=None):
    candidate["answer_field"] = None
    text, candidate["choice_options"] = numbered_choices(action, text, choices or [])
    return await update(
        ctx,
        "pending_financial_actions",
        action["id"],
        {
            "extracted_data": candidate,
            "status": "WAITING_CONFIRMATION",
            "question": text,
            "confirmation_prompt_message_id": message["id"],
            "missing_fields": [],
            "expires_at": now + timedelta(minutes=30),
        },
    )


async def resolve_mutation(ctx, action, text, message, now):
    candidate = action["extracted_data"]
    if not action["target_transaction_id"]:
        options = candidate.get("targets")
        if options and text.strip().isdigit() and 1 <= int(text.strip()) <= len(options):
            targets = [await get(ctx, "transactions", options[int(text.strip()) - 1])]
        else:
            values = amounts(candidate.get("original_text", text))
            targets = [t for t in await rows(ctx, "transactions") if t["status"] != "VOIDED"]
            if len(set(values)) == 1:
                targets = [t for t in targets if format(t["amount"], ".2f") == values[0]]
            elif not options:
                targets = []
            # No automatic selection by recency: matching amount can have multiple results.
        if len(targets) != 1:
            candidate["targets"] = [str(t["id"]) for t in targets[:10]]
            choices = "\n".join(
                f"{i + 1}. {t['transaction_date'].strftime('%d/%m/%Y')} · R$ {t['amount']:.2f} · {t['description']}"
                for i, t in enumerate(targets[:10])
            )
            return await ask(
                ctx,
                action,
                candidate,
                "target",
                ("Qual lançamento? Responda o número:\n" + choices)
                if targets
                else "Não encontrei um único lançamento. Informe o valor ou use a lista de transações.",
                now,
            )
        target = targets[0]
        action = await update(
            ctx,
            "pending_financial_actions",
            action["id"],
            {"target_transaction_id": target["id"], "target_version": target["version"]},
        )
    target = await get(ctx, "transactions", action["target_transaction_id"])
    if action["intent"] == "DELETE_TRANSACTION":
        question = f"Excluir {target['description']}, R$ {target['amount']:.2f}, de {target['transaction_date'].strftime('%d/%m/%Y')}? Responda sim para confirmar."
        return await propose(ctx, action, candidate, question, message, now), question
    correction = candidate.get("correction_text") or text
    if candidate.get("answer_field") == "financial_source":
        correction = text
    parsed = await parser.parse(
        ctx,
        correction,
        now.astimezone(ZoneInfo(ctx.timezone)).date(),
        {"intent": "CREATE_" + target["type"], "fields": candidate.get("fields", {})},
        "financial_source",
    )
    candidate["fields"] = parsed["fields"]
    if "financial_source" not in parsed["fields"]:
        return await ask(
            ctx,
            action,
            candidate,
            "financial_source",
            "Qual é a conta ou cartão correto? Informe também crédito ou débito se houver ambiguidade.",
            now,
        )
    changes = {"financial_source": parsed["fields"]["financial_source"]["value"]}
    candidate["changes"] = changes
    old_source = ledger.to_input(target)["financial_source"]

    async def label(source):
        id = source.get("id") or source.get("account_id") or source.get("source_id")
        row = await get(ctx, "credit_cards" if source["kind"] == "CREDIT_CARD" else "accounts", id)
        return row["name"] + " (" + ("crédito" if source["kind"] == "CREDIT_CARD" else "conta") + ")"

    question = f"Encontrei {target['description']}, R$ {target['amount']:.2f}, de {target['transaction_date'].strftime('%d/%m/%Y')}. Alterar {await label(old_source)} para {await label(changes['financial_source'])}? Responda sim."
    return await propose(ctx, action, candidate, question, message, now), question


async def process(ctx, session, message):
    if message["processing_status"] == "PROCESSED":
        return message["response"]
    require(
        message["processing_status"] == "READY",
        "Mensagem ainda está sendo normalizada.",
        "MESSAGE_NOT_READY",
        409,
    )
    member = await ctx.conn.fetchrow(
        "SELECT role FROM household_members WHERE user_id=$1 AND status='ACTIVE'", session["user_id"]
    )
    require(member and member["role"] != "VIEWER", "Membro sem acesso para registrar.", "FORBIDDEN", 403)
    ctx.user_id = session["user_id"]
    ctx.role = member["role"]
    ctx.origin = "WHATSAPP" if session["channel"] == "WHATSAPP" else "CONVERSATION"
    previous = await ctx.conn.fetchval(
        "SELECT id FROM conversation_messages WHERE session_id=$1 AND sequence<$2 AND processing_status NOT IN ('PROCESSED','FAILED') ORDER BY sequence LIMIT 1",
        session["id"],
        message["sequence"],
    )
    require(not previous, "Aguardando mensagem anterior.", "MESSAGE_NOT_READY", 409)
    text = message["normalized_text"] or ""
    now = datetime.now(timezone.utc)
    today = message["received_at"].astimezone(ZoneInfo(ctx.timezone)).date()
    action = await ctx.conn.fetchrow(
        "SELECT * FROM pending_financial_actions WHERE session_id=$1 AND status IN ('WAITING_INFORMATION','WAITING_CONFIRMATION') FOR UPDATE",
        session["id"],
    )
    action = dict(action) if action else None
    expired = False
    if action and action["expires_at"] <= now:
        await update(ctx, "pending_financial_actions", action["id"], {"status": "EXPIRED"})
        action = None
        expired = True
    if action and action["intent"] == "VERIFY_TRANSCRIPTION":
        if normalize(text) in ("nao", "não"):
            return await response(
                ctx, session, message, action,
                "Envie a frase correta por texto ou grave o áudio novamente.",
            )
        original = action["raw_message"]
        await update(ctx, "pending_financial_actions", action["id"], {"status": "CANCELLED"})
        action = None
        if normalize(text) in ("sim", "confirmo", "correto"):
            text = original
        elif intent(text) == "CANCEL":
            return await response(ctx, session, message, None, "Transcrição cancelada.")
    confidence = (message.get("transcription_metadata") or {}).get("confidence")
    if action is not None and message["kind"] == "AUDIO" and confidence is not None and confidence < 0.7:
        return await response(
            ctx, session, message, action,
            "Não entendi o áudio com segurança. Responda à pergunta pendente por texto ou grave novamente.",
        )
    if action is None and message["kind"] == "AUDIO" and confidence is not None and confidence < 0.7:
        action = await insert(
            ctx, "pending_financial_actions",
            {
                "session_id": session["id"], "user_id": ctx.user_id,
                "intent": "VERIFY_TRANSCRIPTION", "raw_message": text,
                "extracted_data": {"schema_version": 1}, "status": "WAITING_INFORMATION",
                "expires_at": now + timedelta(hours=24),
            },
        )
        return await response(
            ctx, session, message, action,
            f"Ouvi: “{text}”. Está correto? Responda sim ou envie a frase correta.",
        )
    if action and action["intent"] == "IMPORT_INVOICE":
        card_reply = re.fullmatch(r"cart[aã]o\s+(.{2,80})", text.strip(), re.I)
        if card_reply:
            candidate = action["extracted_data"]
            card_name = card_reply.group(1).strip()
            candidate["confirmed_card_name"] = card_name
            candidate["matched_card_id"] = None
            existing_card = await ctx.conn.fetchrow(
                "SELECT id,name FROM credit_cards WHERE lower(name)=lower($1) AND archived_at IS NULL ORDER BY created_at LIMIT 1",
                card_name,
            )
            if existing_card:
                candidate["matched_card_id"] = str(existing_card["id"])
                candidate["matched_card_name"] = existing_card["name"]
            summary = candidate.get("summary") or {}
            from app.workers.runner import invoice_ready, mark_possible_duplicates

            candidate["transactions"] = await mark_possible_duplicates(
                ctx, candidate.get("transactions") or [], candidate.get("matched_card_id")
            )

            ready = invoice_ready(summary, candidate.get("transactions") or [], candidate.get("matched_card_id"),
                                  candidate.get("confirmed_card_name"))
            if ready:
                from app.workers.runner import build_invoice_question_text

                question = build_invoice_question_text(summary, candidate["transactions"], candidate["confirmed_card_name"])
            else:
                question = "Anotei o cartão. Ainda não importei nada: envie imagens com os lançamentos, vencimento e fechamento."
            action = await update(ctx, "pending_financial_actions", action["id"], {
                "extracted_data": candidate,
                "status": "WAITING_CONFIRMATION" if ready else "WAITING_INFORMATION",
                "question": question,
            })
            return await response(ctx, session, message, action, question)
    options = action["extracted_data"].get("choice_options", []) if action else []
    selected = next(
        (
            option
            for index, option in enumerate(options, 1)
            if text.strip() in (str(index), option["id"])
        ),
        None,
    )
    if selected:
        text = selected["reply"]
    elif options and (text.strip().isdigit() or text.strip().startswith("choice:")):
        return await response(ctx, session, message, action, "Essa opção não está disponível. " + action["question"])
    exception_reply = normalize(text)
    explicit_exception = exception_reply in ("confirmar duplicados", "confirmar parcial", "confirmar mesmo assim")
    detected = "CONFIRM" if explicit_exception else intent(text)
    is_whatsapp = session.get("channel") == "WHATSAPP"
    if action and action["intent"] == "IMPORT_INVOICE" and detected not in ("CONFIRM", "CANCEL"):
        from app.modules.ingestion.invoice_parser import parse_money
        from app.workers.runner import (
            build_invoice_header_text,
            build_invoice_question_text,
            invoice_ready,
            mark_possible_duplicates,
        )

        candidate = action["extracted_data"]
        items = list(candidate.get("transactions") or [])
        edit = re.fullmatch(r"corrigir\s+(\d+)\s+(?:para\s+)?(?:R\$\s*)?([\d.,]+)", text.strip(), re.I)
        remove_item = re.fullmatch(r"remover\s+(\d+)", text.strip(), re.I)
        category_edit = re.fullmatch(r"categoria\s+(\d+)\s+(.{2,80})", text.strip(), re.I)
        add_item = re.fullmatch(
            r"adicionar\s+(\d{1,2}/\d{1,2}/\d{4})\s+(.{2,160}?)\s+(?:R\$\s*)?([\d.,]+)",
            text.strip(), re.I,
        )
        if edit or remove_item or category_edit or add_item:
            visible_indexes = [i for i, item in enumerate(items) if item.get("type") != "PAYMENT_OR_CREDIT"]
            visible_index = int((edit or remove_item or category_edit).group(1)) - 1 if not add_item else -1
            if not add_item and not 0 <= visible_index < len(visible_indexes):
                return await response(ctx, session, message, action, "Número de item inválido. " + action["question"])
            index = visible_indexes[visible_index] if not add_item else -1
            if edit:
                amount = parse_money(edit.group(2))
                if amount is None:
                    return await response(ctx, session, message, action, "Valor inválido. Use, por exemplo: corrigir 2 34,17.")
                items[index]["amount"] = amount
            elif remove_item:
                items.pop(index)
            elif category_edit:
                items[index]["category_name"] = category_edit.group(2).strip()
                items[index]["category_source"] = "user_correction"
            else:
                from app.modules.categorization.merchant_classifier import classify_merchant

                amount = parse_money(add_item.group(3))
                try:
                    item_date = datetime.strptime(add_item.group(1), "%d/%m/%Y").date()
                except ValueError:
                    item_date = None
                if amount is None or item_date is None:
                    return await response(ctx, session, message, action,
                                          "Data ou valor inválido. Use: adicionar 01/08/2026 AMAZON BR 34,17.")
                description = add_item.group(2).strip()
                category = await classify_merchant(ctx, description)
                items.append({"date": item_date.isoformat(), "description": description, "amount": amount,
                              "type": "EXPENSE", "category_name": category["category_name"],
                              "category_source": category["source"]})
            candidate["transactions"] = await mark_possible_duplicates(
                ctx, items, candidate.get("matched_card_id")
            )
            summary = candidate.get("summary") or {}
            card_name = candidate.get("confirmed_card_name") or candidate.get("matched_card_name") or "Cartão de Crédito"
            ready = invoice_ready(summary, items, candidate.get("matched_card_id"),
                                  candidate.get("confirmed_card_name") or candidate.get("issuer"))
            question = (build_invoice_question_text(summary, items, card_name) if ready
                        else build_invoice_header_text(summary, card_name, bool(candidate.get("matched_card_id"))))
            action = await update(ctx, "pending_financial_actions", action["id"], {
                "extracted_data": candidate,
                "status": "WAITING_CONFIRMATION" if ready else "WAITING_INFORMATION",
                "question": question,
            })
            change = ("Valor corrigido. " if edit else "Item removido. " if remove_item
                      else "Categoria corrigida. " if category_edit else "Item adicionado. ")
            return await response(ctx, session, message, action, change + question)
        if detected == "UNKNOWN":
            return await response(
                ctx, session, message, action,
                "Não entendi a resposta e não importei nada. "
                "Envie mais imagens, informe ‘cartão Nome’, use ‘corrigir 2 34,17’, "
                "‘categoria 2 Supermercado’, ‘adicionar 01/08/2026 AMAZON BR 34,17’, "
                "‘remover 2’, ‘sim’ ou ‘cancelar’.\n"
                + (action.get("question") or ""),
            )
    if is_whatsapp and not action and detected == "UNKNOWN":
        if session.get("whatsapp_group_id"):
            return await response(
                ctx, session, message, None,
                "Não entendi o pedido e não importei nada. Envie uma foto nítida da fatura, "
                "ou escreva, por exemplo, ‘Gastei 35 no mercado no cartão X’ ou ‘quanto gastei este mês?’."
            )
        await update(ctx, "conversation_messages", message["id"], {"processing_status": "PROCESSED", "processed_at": now})
        return None
    if detected == "CANCEL":
        if action:
            action = await update(ctx, "pending_financial_actions", action["id"], {"status": "CANCELLED"})
            return await response(
                ctx,
                session,
                message,
                action,
                "Importação cancelada. Nenhum item foi registrado."
                if action["intent"] == "IMPORT_INVOICE" else "Lançamento pendente cancelado.",
            )
        if is_whatsapp:
            if session.get("whatsapp_group_id"):
                return await response(ctx, session, message, None, "Não há importação ou lançamento pendente para cancelar.")
            await update(
                ctx,
                "conversation_messages",
                message["id"],
                {
                    "processing_status": "PROCESSED",
                    "processed_at": now,
                },
            )
            return None
        return await response(
            ctx,
            session,
            message,
            action,
            "Não há lançamento pendente.",
        )
    if detected == "CONFIRM":
        if action and action["intent"] == "IMPORT_INVOICE" and action["status"] == "WAITING_INFORMATION":
            return await response(
                ctx, session, message, action,
                "Ainda não importei a fatura: faltam informações. " + (action.get("question") or "Envie outra imagem legível."),
            )
        if (
            action
            and action["status"] == "WAITING_INFORMATION"
            and action["extracted_data"].get("answer_field") == "transaction_date"
        ):
            candidate = action["extracted_data"]
            candidate["fields"]["transaction_date"] = evidence(
                candidate.get("proposed_date", today.isoformat()), "user_confirmed"
            )
            action["extracted_data"] = candidate
        elif action and action["status"] == "WAITING_CONFIRMATION":
            if action["intent"] == "IMPORT_INVOICE":
                from app.workers.runner import invoice_difference

                items = action["extracted_data"].get("transactions", [])
                has_duplicate = any(item.get("possible_duplicate") for item in items)
                difference = invoice_difference(action["extracted_data"].get("summary") or {}, items)
                if (has_duplicate or difference not in (None, 0)) and (
                    not explicit_exception or
                    (difference not in (None, 0) and exception_reply == "confirmar duplicados")
                ):
                    return await response(
                        ctx, session, message, action,
                        "Não importei: a soma diverge da fatura ou há possíveis duplicatas. "
                        "Corrija, envie mais imagens ou responda *confirmar mesmo assim* após conferir.\n"
                        + (action.get("question") or ""),
                    )
            if action["target_transaction_id"]:
                target = await get(ctx, "transactions", action["target_transaction_id"])
                if target["version"] != action["target_version"]:
                    action = await update(
                        ctx, "pending_financial_actions", action["id"], {"status": "CANCELLED"}
                    )
                    return await response(
                        ctx,
                        session,
                        message,
                        action,
                        "O lançamento mudou desde a proposta. Solicite a correção novamente.",
                    )
            if action["intent"] == "IMPORT_INVOICE":
                try:
                    async with ctx.conn.transaction():
                        action, result = await complete(ctx, action)
                except (DomainError, ValueError) as exc:
                    detail = exc.message if isinstance(exc, DomainError) else "data ou valor inválido"
                    return await response(
                        ctx, session, message, action,
                        f"Não importei a fatura: {detail}. Confira a proposta ou envie *cancelar*.",
                    )
            else:
                action, result = await complete(ctx, action)
            if action["intent"] == "IMPORT_INVOICE":
                msg = f"✅ *{result['imported_count']} lançamentos* da fatura importados com sucesso no cartão *{result['card_name']}*!"
                return await response(ctx, session, message, action, msg, result)
            return await response(
                ctx, session, message, action, "✅ Operação confirmada e registrada.", result
            )
        else:
            if is_whatsapp and session.get("whatsapp_group_id"):
                return await response(ctx, session, message, None, "Não há importação ou lançamento aguardando confirmação.")
            if is_whatsapp:
                await update(ctx, "conversation_messages", message["id"], {"processing_status": "PROCESSED", "processed_at": now})
                return None
            return await response(
                ctx,
                session,
                message,
                None,
                "A proposta expirou. Envie o lançamento novamente."
                if expired
                else "Não há proposta vigente para confirmar.",
            )
    if detected.startswith("QUERY_"):
        from app.modules.conversations.queries import query

        answer = await query(ctx, detected, text, today)
        return await response(ctx, session, message, None, answer)
    if action and detected in (
        "CREATE_EXPENSE",
        "CREATE_INCOME",
        "CREATE_TRANSFER",
        "CREATE_GOAL",
        "CREATE_BUDGET",
    ):
        candidate = action["extracted_data"]
        candidate["deferred_text"] = text
        action = await update(ctx, "pending_financial_actions", action["id"], {"extracted_data": candidate})
        return await response(
            ctx,
            session,
            message,
            action,
            "Já existe um lançamento pendente. Responda “trocar” para cancelar o atual e iniciar este, ou continue respondendo à pergunta anterior.",
        )
    if action and normalize(text) == "trocar" and action["extracted_data"].get("deferred_text"):
        text = action["extracted_data"]["deferred_text"]
        detected = intent(text)
        await update(ctx, "pending_financial_actions", action["id"], {"status": "CANCELLED"})
        action = None
    if not action:
        if detected not in (
            "CREATE_EXPENSE",
            "CREATE_INCOME",
            "CREATE_TRANSFER",
            "UPDATE_TRANSACTION",
            "DELETE_TRANSACTION",
            "CREATE_GOAL",
            "CREATE_BUDGET",
        ):
            if is_whatsapp:
                await update(
                    ctx,
                    "conversation_messages",
                    message["id"],
                    {
                        "processing_status": "PROCESSED",
                        "processed_at": now,
                    },
                )
                return None
            return await response(
                ctx,
                session,
                message,
                None,
                "Não consegui identificar um lançamento. Informe valor, data e conta ou cartão. Exemplo: “Gastei 128 de gasolina hoje no crédito Nubank”.",
            )
        candidate = {"schema_version": 1, "intent": detected, "fields": {}, "original_text": text}
        if detected == "UPDATE_TRANSACTION":
            candidate["correction_text"] = re.split(r"\bfoi\b", text, flags=re.I)[-1]
        action = await insert(
            ctx,
            "pending_financial_actions",
            {
                "session_id": session["id"],
                "user_id": ctx.user_id,
                "intent": detected,
                "raw_message": text,
                "extracted_data": candidate,
                "status": "WAITING_INFORMATION",
                "expires_at": now + timedelta(hours=24),
            },
        )
    if action["intent"] in ("UPDATE_TRANSACTION", "DELETE_TRANSACTION"):
        action, question = await resolve_mutation(ctx, action, text, message, now)
        return await response(ctx, session, message, action, question)
    if action["intent"] in ("CREATE_GOAL", "CREATE_BUDGET"):
        from app.modules.conversations.planning import handle_planning

        action, question = await handle_planning(ctx, action, text, message, now)
        return await response(ctx, session, message, action, question)
    parse_today = action["created_at"].astimezone(ZoneInfo(ctx.timezone)).date() if action["intent"] == "CREATE_INCOME" else today
    candidate = await parser.parse(
        ctx, text, parse_today, action["extracted_data"], action["extracted_data"].get("answer_field")
    )
    fields = candidate["fields"]
    if detected == "CONFIRM" and "transaction_date" in action["extracted_data"].get("fields", {}):
        fields["transaction_date"] = action["extracted_data"]["fields"]["transaction_date"]
    is_income = fields.get("type", {}).get("value") == "INCOME"
    required = ["amount", "responsible_user_id", "category_id", "financial_source", "transaction_date"] if is_income else ["amount", "financial_source", "transaction_date"]
    if fields.get("type", {}).get("value") == "EXPENSE":
        required.append("category_id")
    for field in required:
        item = fields.get(field)
        if (
            item is None
            or item.get("requires_confirmation")
            or field in candidate.get("ambiguous_fields", [])
        ):
            choices = None
            questions = {
                "amount": "Qual foi o valor exato?",
                "financial_source": "Qual conta ou cartão foi utilizado? Se necessário, informe crédito ou débito.",
                "transaction_date": f"Foi hoje, {today.strftime('%d/%m/%Y')}? Responda sim ou informe a data completa.",
                "category_id": "O que você comprou? Informe a categoria ou responda “Sem categoria”.",
            }
            if is_income:
                if field == "responsible_user_id":
                    people = await ctx.conn.fetch(
                        "SELECT u.display_name FROM household_members m JOIN users u ON u.id=m.user_id WHERE m.status='ACTIVE' ORDER BY u.display_name"
                    )
                    questions[field] = "De quem é esta receita?"
                    choices = [(p["display_name"], p["display_name"]) for p in people]
                elif field == "category_id":
                    person = fields.get("responsible_user_id", {}).get("value")
                    profiles = await ctx.conn.fetch(
                        "SELECT DISTINCT c.name FROM income_activity_profiles p JOIN categories c ON c.id=p.category_id WHERE ($1::uuid IS NULL OR p.user_id=$1::uuid) ORDER BY c.name",
                        person,
                    )
                    questions[field] = "De qual trabalho veio a receita?"
                    choices = [(p["name"], p["name"]) for p in profiles] or None
                elif field == "financial_source":
                    accounts = [account for account in await rows(ctx, "accounts") if not account["archived_at"]]
                    questions[field] = (
                        "Em qual conta o valor entrou?"
                        if accounts
                        else "Ainda não há conta cadastrada. Cadastre uma no aplicativo e depois informe aqui o nome dela."
                    )
                    choices = [(account["name"], account["name"]) for account in accounts[:10]] if len(accounts) <= 10 else None
            if field == "transaction_date":
                candidate["proposed_date"] = item["value"] if item and item["value"] else today.isoformat()
                if item:
                    questions[field] = (
                        f"Confirma a data {candidate['proposed_date']}? Responda sim ou informe outra data completa."
                    )
            action, question = await ask(ctx, action, candidate, field, questions[field], now, choices)
            return await response(ctx, session, message, action, question)
    # Fully explicit fields may execute; inferred/historical material always asks first.
    material_suggested = any(fields[k].get("source") == "historical_pattern" for k in required)
    action = await update(
        ctx,
        "pending_financial_actions",
        action["id"],
        {"extracted_data": candidate, "missing_fields": [], "ambiguous_fields": []},
    )
    if is_income:
        person = await ctx.conn.fetchval(
            "SELECT display_name FROM users WHERE id=$1", UUID(fields["responsible_user_id"]["value"])
        )
        category = await get(ctx, "categories", fields["category_id"]["value"])
        source = fields["financial_source"]["value"]
        account = await get(ctx, "accounts", source.get("id") or source.get("source_id"))
        value = fields["amount"]["value"]
        question = (
            f"Confirma esta receita? R$ {value} · {person} · {category['name']} · "
            f"conta {account['name']} · {fields['transaction_date']['value']} · "
            f"{fields['description']['value']}."
        )
        action = await propose(
            ctx, action, candidate, question, message, now,
            [("Confirmar e registrar", "sim"), ("Cancelar", "cancelar")],
        )
        return await response(ctx, session, message, action, action["question"])
    if material_suggested:
        question = "Confirma o lançamento sugerido? " + str({k: v["value"] for k, v in fields.items()})
        action = await propose(ctx, action, candidate, question, message, now)
        return await response(ctx, session, message, action, question)
    action, result = await complete(ctx, action)
    value = fields["amount"]["value"]
    source = fields["financial_source"]["value"]
    source_id = source.get("id") or source.get("source_id")
    label = (await get(ctx, "credit_cards" if source["kind"] == "CREDIT_CARD" else "accounts", source_id))[
        "name"
    ]
    category = (
        await get(ctx, "categories", fields["category_id"]["value"])
        if fields.get("category_id", {}).get("value")
        else None
    )
    question = f"✅ R$ {value} registrado em {category['name'] if category else 'Sem categoria'} — {label}, {fields['transaction_date']['value']}."
    return await response(ctx, session, message, action, question, result)
