from decimal import Decimal

from app.core.db import rows
from app.modules.analytics import forecast, service
from app.modules.ledger.service import account_balances, invoice_balance


async def query(ctx, intent, text, today):
    if intent == "QUERY_BALANCE":
        balances = await account_balances(ctx)
        if not balances:
            return "Nenhuma conta cadastrada."
        return "\n".join(f"{a['name']}: R$ {a['balance']:.2f}" for a in balances)
    if intent == "QUERY_NET_WORTH":
        summary = await service.summary(ctx)
        return f"Patrimônio líquido atual: R$ {summary['net_worth']:.2f}."
    if intent == "QUERY_CASHFLOW":
        result = await forecast.cashflow(ctx)
        return f"Projeção em 90 dias: R$ {result['daily'][-1]['balance']:.2f}. Cenário baseado apenas em compromissos cadastrados; não é saldo realizado."
    if intent == "QUERY_CREDIT_CARD":
        invoices = await rows(ctx, "credit_card_invoices")
        if not invoices:
            return "Nenhuma fatura cadastrada."
        return "\n".join(
            f"Fatura com vencimento {i['due_date'].strftime('%d/%m/%Y')}: R$ {await invoice_balance(ctx, i['id']):.2f}"
            for i in invoices
        )
    if intent == "QUERY_BUDGET":
        from app.modules.planning.service import budget_detail

        budgets = [b for b in await rows(ctx, "budgets") if b["period_start"] <= today <= b["period_end"]]
        if not budgets:
            return "Nenhum orçamento cadastrado para o período atual."
        detail = await budget_detail(ctx, budgets[0]["id"])
        actual = sum((line["actual"] for line in detail["categories"]), Decimal(0))
        limit = sum((line["amount"] for line in detail["categories"]), Decimal(0))
        return f"Orçamento atual: R$ {actual:.2f} realizados de R$ {limit:.2f}."
    from app.modules.resources import normalize

    normalized = normalize(text)
    # The default period is disclosed, never presented as an unbounded total.
    if any(word in normalized for word in ("ano", "semana", "passado", "ontem")):
        return "Informe o período pelo filtro de datas no dashboard; esta consulta conversacional resume o mês atual."
    result = await service.summary(ctx, today.replace(day=1), today)
    field = "income" if intent == "QUERY_INCOME" else "expenses"
    return f"{'Receitas' if field == 'income' else 'Despesas'} de {today.replace(day=1).strftime('%d/%m')} até {today.strftime('%d/%m/%Y')}, por competência: R$ {result[field]:.2f}."
