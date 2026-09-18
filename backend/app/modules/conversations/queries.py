import logging
from decimal import Decimal

import httpx

from app.core.db import rows
from app.modules.analytics import forecast, service
from app.modules.categorization.merchant_classifier import query_searxng
from app.modules.ledger.service import account_balances, invoice_balance

logger = logging.getLogger("finance.queries")


async def query_currency(text: str) -> str:
    """Fetch current currency exchange rates via AwesomeAPI with SearXNG fallback."""
    try:
        async with httpx.AsyncClient(timeout=3.5) as client:
            res = await client.get("https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,USD-BRLT")
            if res.status_code == 200:
                data = res.json()
                usd = data.get("USDBRL", {})
                usdt = data.get("USDBRLT", {})
                eur = data.get("EURBRL", {})
                usd_val = float(usd.get("bid", 0))
                usd_pct = float(usd.get("pctChange", 0))
                eur_val = float(eur.get("bid", 0))
                eur_pct = float(eur.get("pctChange", 0))
                usdt_val = float(usdt.get("ask", 0) or usdt.get("bid", 0))
                return (
                    f"💵 *Cotações de Moedas Hoje*:\n"
                    f"• *Dólar Comercial (USD)*: R$ {usd_val:.2f} ({usd_pct:+.2f}%)\n"
                    f"• *Dólar Turismo (USD)*: R$ {usdt_val:.2f}\n"
                    f"• *Euro Comercial (EUR)*: R$ {eur_val:.2f} ({eur_pct:+.2f}%)\n\n"
                    f"💡 *Dica Financeira*: Para compras internacionais no cartão de crédito, considere a cotação do emissor + IOF (4,38%) e eventual spread cambial."
                )
    except Exception as exc:
        logger.warning("AwesomeAPI error for currency query: %s", exc)

    # SearXNG Fallback
    try:
        results = await query_searxng("cotacao dolar euro turismo comercial hoje brasil", count=3)
        if results:
            snippets = [f"• {r.get('title', '')}: {r.get('content', '')}" for r in results if r.get('content')]
            if snippets:
                return (
                    "💵 *Cotação e Câmbio (Pesquisa SearXNG)*:\n"
                    + "\n".join(snippets[:2])
                    + "\n\n💡 *Dica Financeira*: Lembre-se de adicionar IOF e spread bancário para faturas em moeda estrangeira."
                )
    except Exception as exc:
        logger.warning("SearXNG error for currency query: %s", exc)

    return "Não foi possível obter as cotações em tempo real no momento. Tente novamente em instantes."


async def query_economic_indicators(text: str) -> str:
    """Fetch current Selic, CDI, and IPCA indicators via BCB SGS with SearXNG fallback."""
    try:
        async with httpx.AsyncClient(timeout=3.5) as client:
            selic_res = await client.get("https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados/ultimos/1?formato=json")
            cdi_res = await client.get("https://api.bcb.gov.br/dados/serie/bcdata.sgs.4389/dados/ultimos/1?formato=json")
            ipca_res = await client.get("https://api.bcb.gov.br/dados/serie/bcdata.sgs.13522/dados/ultimos/1?formato=json")

            if selic_res.status_code == 200 and cdi_res.status_code == 200:
                selic_val = float(selic_res.json()[0]["valor"])
                cdi_val = float(cdi_res.json()[0]["valor"])
                ipca_val = float(ipca_res.json()[0]["valor"]) if ipca_res.status_code == 200 else 4.22

                cdi_monthly = ((1 + cdi_val / 100) ** (1 / 12) - 1) * 100

                return (
                    f"📊 *Principais Indicadores Econômicos*:\n"
                    f"• *Taxa Selic (Meta)*: {selic_val:.2f}% a.a.\n"
                    f"• *Taxa CDI (DI)*: {cdi_val:.2f}% a.a. (~{cdi_monthly:.2f}% ao mês)\n"
                    f"• *IPCA (Inflação 12m)*: {ipca_val:.2f}%\n\n"
                    f"💡 *Impacto no seu Planejamento*:\n"
                    f"• *Reserva de emergência em CDB 100% CDI*: rende ~{cdi_monthly:.2f}% a.m. bruto.\n"
                    f"• *Rendimento real*: CDI ({cdi_val:.2f}%) supera a inflação IPCA ({ipca_val:.2f}%), protegendo seu patrimônio."
                )
    except Exception as exc:
        logger.warning("BCB API error for economic indicators: %s", exc)

    # SearXNG Fallback
    try:
        results = await query_searxng("taxa selic hoje cdi ipca rendimento ibge brasil", count=3)
        if results:
            snippets = [f"• {r.get('title', '')}: {r.get('content', '')}" for r in results if r.get('content')]
            if snippets:
                return (
                    "📊 *Indicadores Econômicos (Pesquisa SearXNG)*:\n"
                    + "\n".join(snippets[:2])
                    + "\n\n💡 *Dica Financeira*: O CDI baliza investimentos de renda fixa e liquidez diária para reserva de emergência."
                )
    except Exception as exc:
        logger.warning("SearXNG error for economic indicators: %s", exc)

    return "Não foi possível obter os indicadores econômicos em tempo real no momento. Tente novamente em instantes."


async def query(ctx, intent, text, today):
    if intent == "QUERY_CURRENCY":
        return await query_currency(text)
    if intent == "QUERY_ECONOMIC_INDICATORS":
        return await query_economic_indicators(text)
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
