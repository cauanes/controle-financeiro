import re
from datetime import date, timedelta
from typing import Protocol

from app.core.db import rows
from app.core.money import money
from app.modules.categorization.service import categorize, contains
from app.modules.resources import normalize

NUMBERS = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
    "cem": 100,
    "cento": 100,
    "duzentos": 200,
    "trezentos": 300,
    "quatrocentos": 400,
    "quinhentos": 500,
    "seiscentos": 600,
    "setecentos": 700,
    "oitocentos": 800,
    "novecentos": 900,
    "mil": 1000,
}


class FinancialParser(Protocol):
    async def parse(self, ctx, text, today, existing=None, answer_field=None): ...


def evidence(value, source="user_explicit", confidence=1.0):
    return {"value": value, "source": source, "confidence": confidence, "requires_confirmation": False}


def intent(text):
    value = normalize(text)
    if value in ("sim", "confirmo", "confirmar", "isso", "correto", "pode registrar"):
        return "CONFIRM"
    if value in ("cancelar", "cancela", "nao", "deixa pra la"):
        return "CANCEL"
    if re.search(r"\b(apaga|apagar|exclui|excluir|delete)\b", value):
        return "DELETE_TRANSACTION"
    if re.search(r"\b(corrige|corrigir|altera|alterar|nao foi|aquele|aquela)\b", value):
        return "UPDATE_TRANSACTION"
    if re.search(r"\b(saldo|disponivel)\b", value):
        return "QUERY_BALANCE"
    if re.search(r"\b(patrimonio)\b", value):
        return "QUERY_NET_WORTH"
    if re.search(r"\b(fluxo de caixa)\b", value):
        return "QUERY_CASHFLOW"
    if re.search(r"\b(quanto|quais|mostr[ae]|consult[ae]|listar)\b", value):
        if "orcamento" in value:
            return "QUERY_BUDGET"
        if "fatura" in value or "cartao" in value:
            return "QUERY_CREDIT_CARD"
        return "QUERY_INCOME" if "receb" in value or "receita" in value else "QUERY_EXPENSES"
    if re.search(r"\b(simul|amortiz|diagnostic|previsao)", value):
        return "UNSUPPORTED"
    if re.search(r"\b(orcamento)\b", value):
        return "CREATE_BUDGET"
    if re.search(r"\b(meta|objetivo)\b", value):
        return "CREATE_GOAL"
    if re.search(r"\b(transferi|transferencia|transferir)\b", value):
        return "CREATE_TRANSFER"
    if re.search(r"\b(recebi|recebimento|receita|salario)\b", value):
        return "CREATE_INCOME"
    if re.search(r"\b(gastei|gasto|paguei|comprei|compra|coloca|registra|anota)\b", value) or re.search(
        r"\d.*\b(mercado|gasolina|amazon|reais|credito|debito)\b", value
    ):
        return "CREATE_EXPENSE"
    return "UNKNOWN"


def amounts(text):
    value = normalize(text)
    # Dates and installment counts must not become amounts.
    value = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", " ", value)
    value = re.sub(r"\b\d+\s*(?:x|parcelas?)\b", " ", value)
    numeric = re.findall(
        r"(?<![\w/])\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|(?<![\w/])\d+(?:[,.]\d{1,2})?(?![\d/])", value
    )
    if numeric:
        result = []
        for token in numeric:
            token = (
                token.replace(".", "").replace(",", ".")
                if "," in token or re.fullmatch(r"\d{1,3}(?:\.\d{3})+", token)
                else token
            )
            try:
                result.append(format(money(token, positive=True), ".2f"))
            except Exception:
                pass
        return result
    match = re.search(r"((?:(?:" + "|".join(NUMBERS) + r")\s+(?:e\s+)?)+)(?:reais?|real)\b", value + " ")
    if not match:
        return []
    total = 0
    current = 0
    for word in match[1].split():
        if word == "mil":
            total += (current or 1) * 1000
            current = 0
        elif word in NUMBERS:
            current += NUMBERS[word]
    return [format(money(str(total + current), positive=True), ".2f")]


def parse_date(text, today):
    text = normalize(text)
    found = []
    for token in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text):
        try:
            found.append(date.fromisoformat(token).isoformat())
        except ValueError:
            return None, True
    for day, month, year in re.findall(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b", text):
        # Missing year is a proposal requiring confirmation.
        try:
            found.append(date(int(year) if year else today.year, int(month), int(day)).isoformat())
        except ValueError:
            return None, True
        if not year:
            return found[-1], True
    if contains(text, "hoje"):
        found.append(today.isoformat())
    if contains(text, "ontem"):
        found.append((today - timedelta(days=1)).isoformat())
    if contains(text, "amanha"):
        found.append((today + timedelta(days=1)).isoformat())
    return (found[0], False) if len(set(found)) == 1 else (None, len(found) > 1)


class RuleParser:
    async def parse(self, ctx, text, today, existing=None, answer_field=None):
        candidate = {"schema_version": 1, "intent": intent(text), "fields": {}, "ambiguous_fields": []}
        if existing:
            candidate = {**existing, "fields": {**existing.get("fields", {})}, "ambiguous_fields": []}
        fields = candidate["fields"]
        norm = normalize(text)
        kind = {"CREATE_EXPENSE": "EXPENSE", "CREATE_INCOME": "INCOME", "CREATE_TRANSFER": "TRANSFER"}.get(
            candidate["intent"]
        )
        if kind:
            fields["type"] = evidence(kind)
        if "amount" not in fields or answer_field == "amount":
            values = amounts(text)
            if len(set(values)) == 1:
                fields["amount"] = evidence(values[0])
            elif len(values) > 1:
                candidate["ambiguous_fields"].append("amount")
                fields.pop("amount", None)
        d, uncertain = parse_date(text, today)
        if d:
            fields["transaction_date"] = evidence(d)
            fields["transaction_date"]["requires_confirmation"] = uncertain
        elif uncertain:
            candidate["ambiguous_fields"].append("transaction_date")
        if not fields.get("description"):
            fields["description"] = evidence(text[:500])
        # Never choose a source just because there is one available.
        accounts = [a for a in await rows(ctx, "accounts") if not a["archived_at"]]
        cards = [c for c in await rows(ctx, "credit_cards") if not c["archived_at"]]
        source_matches = []
        payment = None
        if contains(norm, "credito"):
            payment = "CREDIT_CARD"
        if (
            contains(norm, "debito")
            or contains(norm, "pix")
            or contains(norm, "dinheiro")
            or contains(norm, "conta")
        ):
            payment = "ACCOUNT"
        if payment:
            fields["payment_method"] = evidence(payment)
        else:
            payment = fields.get("payment_method", {}).get("value")
        if kind == "INCOME":
            payment = "ACCOUNT"
        if kind == "TRANSFER":
            named = [a for a in accounts if contains(norm, a["name"])]
            if len(named) == 2:
                positions = sorted(named, key=lambda a: norm.index(normalize(a["name"])))
                # Direction only inferred from explicit de/da/do ... para/pra ... wording.
                if re.search(r"\b(de|da|do)\b.*\b(para|pra)\b", norm):
                    fields["financial_source"] = evidence(
                        {
                            "kind": "ACCOUNT_TRANSFER",
                            "source_id": str(positions[0]["id"]),
                            "destination_id": str(positions[1]["id"]),
                        }
                    )
            return candidate
        for source_kind, collection in [("ACCOUNT", accounts), ("CREDIT_CARD", cards)]:
            for item in collection:
                if contains(norm, item["name"]) and (payment is None or payment == source_kind):
                    source_matches.append({"kind": source_kind, "id": str(item["id"]), "name": item["name"]})
        if (
            not source_matches
            and answer_field == "financial_source"
            and payment
            and candidate.get("source_options")
        ):
            source_matches = [s for s in candidate["source_options"] if s["kind"] == payment]
        if len(source_matches) == 1:
            s = source_matches[0]
            fields["financial_source"] = evidence({k: s[k] for k in ("kind", "id")})
            candidate.pop("source_options", None)
        elif len(source_matches) > 1:
            candidate["source_options"] = source_matches
            fields.pop("financial_source", None)
            candidate["ambiguous_fields"].append("financial_source")
        if contains(norm, "sem categoria"):
            fields["category_id"] = evidence(None)
        elif kind in ("EXPENSE", "INCOME"):
            category = await categorize(ctx, text, kind)
            if category:
                fields["category_id"] = category
            elif answer_field == "category_id":
                named = [
                    c
                    for c in await rows(ctx, "categories")
                    if not c["archived_at"] and c["kind"] == kind and normalize(c["name"]) == norm
                ]
                if len(named) == 1:
                    fields["category_id"] = evidence(str(named[0]["id"]))
        for merchant in await rows(ctx, "merchants"):
            if not merchant["archived_at"] and contains(norm, merchant["name"]):
                fields["merchant_id"] = evidence(str(merchant["id"]))
        if contains(norm, "amazon") and "category_id" not in fields:
            candidate["merchant_hint"] = "Amazon"
        return candidate
