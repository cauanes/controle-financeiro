from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import audit, emit, get, insert, rows, update
from app.core.errors import require
from app.core.money import add_months, installments, invoice_dates
from app.core.schemas import Transaction


async def active(ctx, table, id):
    require(id is not None, "Selecione a fonte financeira.")
    row = await get(ctx, table, id)
    require(not row.get("archived_at"), "Registro arquivado não pode ser utilizado.")
    return row


async def validate(ctx, body: Transaction):
    source = body.financial_source
    expected = {
        "ACCOUNT": {"id"},
        "CREDIT_CARD": {"id"},
        "ACCOUNT_TRANSFER": {"source_id", "destination_id"},
        "INVOICE_PAYMENT": {"account_id", "invoice_id"},
    }[source.kind]
    actual = {k for k, v in source.model_dump().items() if k != "kind" and v is not None}
    require(actual == expected, "Campos incompatíveis com a fonte financeira selecionada.")
    values = body.model_dump(exclude={"financial_source", "installment_count"})
    values["competence_date"] = body.competence_date or body.transaction_date
    values.update(
        account_id=None, destination_account_id=None, credit_card_id=None, invoice_id=None, subtype=None
    )
    if body.transaction_date > ctx.today():
        values["status"] = "PLANNED"
    if source.kind == "ACCOUNT":
        require(body.type in ("EXPENSE", "INCOME"), "Transferência precisa de origem e destino.")
        await active(ctx, "accounts", source.id)
        values["account_id"] = source.id
    elif source.kind == "CREDIT_CARD":
        require(body.type == "EXPENSE", "Cartão aceita apenas despesa neste fluxo.")
        await active(ctx, "credit_cards", source.id)
        values["credit_card_id"] = source.id
    elif source.kind == "ACCOUNT_TRANSFER":
        require(
            body.type == "TRANSFER" and source.source_id != source.destination_id,
            "Transferência exige contas distintas.",
        )
        await active(ctx, "accounts", source.source_id)
        await active(ctx, "accounts", source.destination_id)
        values.update(account_id=source.source_id, destination_account_id=source.destination_id)
    else:
        require(body.type == "TRANSFER", "Pagamento de fatura é transferência.")
        await active(ctx, "accounts", source.account_id)
        await get(ctx, "credit_card_invoices", source.invoice_id, lock=True)
        values.update(account_id=source.account_id, invoice_id=source.invoice_id, subtype="INVOICE_PAYMENT")
    require(body.installment_count == 1 or source.kind == "CREDIT_CARD", "Parcelamento exige cartão.")
    if body.type == "TRANSFER":
        require(not body.category_id, "Transferência não possui categoria.")
    if body.category_id:
        category = await active(ctx, "categories", body.category_id)
        require(category["kind"] == body.type, "Categoria incompatível com o tipo.")
    if body.merchant_id:
        await active(ctx, "merchants", body.merchant_id)
    if body.responsible_user_id:
        member = await ctx.conn.fetchrow(
            "SELECT * FROM household_members WHERE user_id=$1 AND status='ACTIVE'", body.responsible_user_id
        )
        require(member, "Responsável não é membro ativo.")
    for account_id in (values["account_id"], values["destination_account_id"]):
        if account_id:
            account = await get(ctx, "accounts", account_id)
            require(
                body.transaction_date >= account["opening_balance_date"],
                "Data anterior ao saldo de abertura da conta.",
            )
    return values


async def ensure_invoice(ctx, card_id, purchased, offset=0):
    card = await active(ctx, "credit_cards", card_id)
    closing, due = invoice_dates(purchased, card["closing_day"], card["due_day"], offset)
    current = await ctx.conn.fetchrow(
        "SELECT * FROM credit_card_invoices WHERE credit_card_id=$1 AND closing_date=$2", card_id, closing
    )
    if current:
        return dict(current)
    return await insert(
        ctx,
        "credit_card_invoices",
        {
            "credit_card_id": card_id,
            "period_start": add_months(closing, -1, card["closing_day"]) + timedelta(days=1),
            "closing_date": closing,
            "due_date": due,
        },
    )


async def invoice_balance(ctx, invoice_id, exclude=None):
    return await ctx.conn.fetchval(
        "SELECT COALESCE(sum(CASE WHEN type='EXPENSE' THEN amount ELSE -amount END),0) FROM transactions WHERE invoice_id=$1 AND status='POSTED' AND ($2::uuid IS NULL OR id<>$2)",
        invoice_id,
        exclude,
    )


async def sync_invoice(ctx, invoice_id):
    if not invoice_id:
        return
    invoice = await get(ctx, "credit_card_invoices", invoice_id, lock=True)
    balance = await invoice_balance(ctx, invoice_id)
    require(balance >= 0, "A alteração excederia o total de compras da fatura já paga.")
    paid = await ctx.conn.fetchval(
        "SELECT COALESCE(sum(amount),0) FROM transactions WHERE invoice_id=$1 AND subtype='INVOICE_PAYMENT' AND status='POSTED'",
        invoice_id,
    )
    status = (
        "PAID"
        if balance == 0 and paid
        else "PARTIALLY_PAID"
        if paid
        else "CLOSED"
        if invoice["closing_date"] < ctx.today()
        else "OPEN"
    )
    await update(ctx, "credit_card_invoices", invoice_id, {"status": status})


async def add_source(ctx, tx, source_type, source_key, metadata=None):
    metadata = metadata or {}
    return await insert(
        ctx,
        "transaction_sources",
        {"transaction_id": tx["id"], "source_type": source_type, "source_key": source_key, **metadata},
    )


async def create(
    ctx,
    body: Transaction,
    *,
    source_type="MANUAL",
    source_key=None,
    metadata=None,
    recurring_id=None,
    occurrence_date=None,
    invoice_closing_date=None,
):
    ctx.write()
    await ctx.lock()
    values = await validate(ctx, body)
    if invoice_closing_date is not None:
        require(
            source_type == "INVOICE_OCR" and body.financial_source.kind == "CREDIT_CARD"
            and body.installment_count == 1,
            "Ciclo de fatura explícito só é permitido na importação de uma parcela de cartão.",
        )
    chunks = installments(body.amount, body.installment_count)
    group = uuid4() if len(chunks) > 1 else None
    source_key = source_key or str(uuid4())
    result = []
    for i, amount in enumerate(chunks):
        item = {**values, "amount": amount, "actor_user_id": ctx.user_id}
        if item["credit_card_id"]:
            invoice = await ensure_invoice(
                ctx, item["credit_card_id"], invoice_closing_date or body.transaction_date, i
            )
            item.update(invoice_id=invoice["id"], due_date=invoice["due_date"])
            if invoice_closing_date is not None:
                require(invoice["closing_date"] == invoice_closing_date, "Fechamento não corresponde ao cartão.")
                item["competence_date"] = invoice["closing_date"]
            if group:
                item.update(
                    installment_group_id=group,
                    installment_number=i + 1,
                    installment_count=len(chunks),
                    competence_date=invoice["closing_date"],
                )
        if item["subtype"] == "INVOICE_PAYMENT":
            require(
                item["amount"] <= await invoice_balance(ctx, item["invoice_id"]),
                "Pagamento maior que o saldo da fatura.",
            )
        if recurring_id:
            require(not group, "Recorrência parcelada não é suportada.")
            item.update(recurring_transaction_id=recurring_id, occurrence_date=occurrence_date)
        tx = await insert(ctx, "transactions", item)
        if tx["subtype"] == "INVOICE_PAYMENT":
            await insert(
                ctx,
                "invoice_payments",
                {"invoice_id": tx["invoice_id"], "transaction_id": tx["id"], "amount": tx["amount"]},
            )
        await add_source(ctx, tx, source_type, source_key + (f":{i + 1}" if group else ""), metadata)
        await sync_invoice(ctx, tx["invoice_id"])
        await audit(ctx, "CREATE", "transactions", tx)
        await emit(ctx, "TransactionCreated", tx["id"])
        result.append(tx)
    return {"transactions": result, "id": result[0]["id"], "version": result[0]["version"]}


def to_input(tx):
    if tx["credit_card_id"]:
        source = {"kind": "CREDIT_CARD", "id": tx["credit_card_id"]}
    elif tx["subtype"] == "INVOICE_PAYMENT":
        source = {"kind": "INVOICE_PAYMENT", "account_id": tx["account_id"], "invoice_id": tx["invoice_id"]}
    elif tx["destination_account_id"]:
        source = {
            "kind": "ACCOUNT_TRANSFER",
            "source_id": tx["account_id"],
            "destination_id": tx["destination_account_id"],
        }
    else:
        source = {"kind": "ACCOUNT", "id": tx["account_id"]}
    fields = set(Transaction.model_fields) - {"financial_source", "installment_count"}
    return {k: tx[k] for k in fields if k in tx} | {"financial_source": source, "installment_count": 1}


async def patch(ctx, id, changes, version):
    ctx.write()
    await ctx.lock()
    old = await get(ctx, "transactions", id, lock=True)
    require(old["status"] != "VOIDED", "Lançamento excluído não pode ser alterado.")
    require(old["version"] == version, "O lançamento mudou. Recarregue.", "VERSION_CONFLICT", 409)
    require("installment_count" not in changes, "Alterar parcelamento exige recriar a compra explicitamente.")
    merged = to_input(old) | changes
    body = Transaction.model_validate(merged)
    values = await validate(ctx, body)
    if values["credit_card_id"]:
        # Keep the cycle of an installment unless explicitly changing its card/date.
        keep = (
            old["credit_card_id"] == values["credit_card_id"]
            and old["transaction_date"] == values["transaction_date"]
        )
        invoice = (
            await get(ctx, "credit_card_invoices", old["invoice_id"])
            if keep
            else await ensure_invoice(
                ctx, values["credit_card_id"], body.transaction_date, (old["installment_number"] or 1) - 1
            )
        )
        values.update(invoice_id=invoice["id"], due_date=invoice["due_date"])
    require(not old["installment_group_id"] or values["credit_card_id"], "Parcela deve permanecer em cartão.")
    if values["subtype"] == "INVOICE_PAYMENT":
        require(
            values["amount"] <= await invoice_balance(ctx, values["invoice_id"], old["id"]),
            "Pagamento maior que o saldo da fatura.",
        )
    require(
        old["subtype"] == values["subtype"],
        "Não converter pagamento de fatura em outro tipo; exclua e registre explicitamente.",
    )
    material = any(
        values.get(k) != old.get(k)
        for k in ("amount", "transaction_date", "account_id", "credit_card_id", "invoice_id")
    )
    if material and old["reconciliation_status"] == "RECONCILED":
        values["reconciliation_status"] = "NEEDS_REVIEW"
    result = await update(ctx, "transactions", id, values, expected_version=version)
    if values["subtype"] == "INVOICE_PAYMENT":
        payment = await ctx.conn.fetchrow(
            "SELECT id FROM invoice_payments WHERE transaction_id=$1", old["id"]
        )
        await update(
            ctx,
            "invoice_payments",
            payment["id"],
            {"invoice_id": values["invoice_id"], "amount": values["amount"]},
        )
    for invoice_id in {old["invoice_id"], result["invoice_id"]}:
        await sync_invoice(ctx, invoice_id)
    await audit(ctx, "UPDATE", "transactions", result, old)
    await emit(ctx, "TransactionUpdated", result["id"])
    return result


async def void(ctx, id, version, reason):
    ctx.write()
    await ctx.lock()
    require(reason.strip(), "Informe o motivo da exclusão.")
    old = await get(ctx, "transactions", id, lock=True)
    require(old["version"] == version, "O lançamento mudou.", "VERSION_CONFLICT", 409)
    require(old["status"] != "VOIDED", "Lançamento já excluído.", "STATE_CONFLICT", 409)
    result = await update(
        ctx,
        "transactions",
        id,
        {"status": "VOIDED", "voided_at": datetime.now(timezone.utc), "void_reason": reason},
        expected_version=version,
    )
    await sync_invoice(ctx, old["invoice_id"])
    await audit(ctx, "DELETE", "transactions", result, old)
    await emit(ctx, "TransactionDeleted", result["id"])
    return result


async def account_balances(ctx, as_of=None):
    as_of = as_of or ctx.today()
    result = []
    for account in await rows(ctx, "accounts"):
        if account["opening_balance_date"] > as_of:
            continue
        delta = await ctx.conn.fetchval(
            """SELECT COALESCE(sum(CASE WHEN destination_account_id=$1 THEN amount
        WHEN account_id=$1 AND type='INCOME' THEN amount ELSE -amount END),0)
        FROM transactions WHERE status='POSTED' AND transaction_date<=$2 AND (account_id=$1 OR destination_account_id=$1)""",
            account["id"],
            as_of,
        )
        result.append(account | {"balance": account["opening_balance"] + delta})
    return result
