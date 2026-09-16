import re

from app.core.db import rows
from app.modules.resources import normalize

KEYWORDS = {
    "Supermercado": ("mercado", "supermercado"),
    "Combustível": ("gasolina", "combustivel", "posto", "abasteci", "abastecimento"),
    "Livros": ("livro", "livros"),
    "Aluguel": ("aluguel",),
    "Salário": ("salario", "salário"),
}


def contains(text, pattern):
    return bool(re.search(r"(?<!\w)" + re.escape(normalize(pattern)) + r"(?!\w)", normalize(text)))


async def categorize(ctx, text, kind):
    categories = {
        c["id"]: c for c in await rows(ctx, "categories") if not c["archived_at"] and c["kind"] == kind
    }
    matches = []
    for rule in await rows(ctx, "category_rules"):
        if (
            not rule["enabled"]
            or rule["category_id"] not in categories
            or rule["user_id"] not in (None, ctx.user_id)
        ):
            continue
        match = (
            normalize(text) == normalize(rule["pattern"])
            if rule["match_type"] == "EXACT"
            else contains(text, rule["pattern"])
        )
        if match:
            matches.append((1 if rule["user_id"] else 0, rule["priority"], rule))
    if matches:
        matches.sort(key=lambda x: x[:2], reverse=True)
        best = [m[2] for m in matches if m[:2] == matches[0][:2]]
        if len({m["category_id"] for m in best}) == 1:
            rule = best[0]
            return {
                "value": str(rule["category_id"]),
                "confidence": float(rule["confidence"]) if rule["confidence"] is not None else None,
                "source": "keyword_rule",
                "requires_confirmation": rule["confidence"] is None or rule["confidence"] < 0.9,
            }
        return {
            "value": None,
            "confidence": None,
            "source": "conflicting_rules",
            "requires_confirmation": True,
        }
    found = []
    for category in categories.values():
        if any(contains(text, word) for word in KEYWORDS.get(category["name"], ())):
            found.append(category)
    if len(found) == 1:
        return {
            "value": str(found[0]["id"]),
            "confidence": 0.99,
            "source": "keyword_rule",
            "requires_confirmation": False,
        }
    return None
