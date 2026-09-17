import re
from typing import Any

import httpx

from app.core.db import rows
from app.modules.resources import normalize

SEARXNG_URL = "http://127.0.0.1:8888"

# 1. Deterministic Known Merchants / Brands Dictionary (100% offline & fast)
KNOWN_MERCHANT_PATTERNS: dict[str, list[str]] = {
    "Supermercado": [
        "sams club", "sam's club", "carrefour", "pao de acucar", "pão de açúcar", "extra", "assai", "assaí",
        "atacadao", "atacadão", "zaffari", "dia", "muffato", "angeloni", "big", "condor", "supermercado",
        "mercado", "hortifruti", "sacolao", "sacolão", "mambo", "st marche", "natural da terra", "crf"
    ],
    "Alimentação": [
        "happy salgados", "mcdonalds", "mc donald", "burger king", "bk", "ifood", "rappi", "subway",
        "outback", "starbucks", "restaurante", "pizzaria", "padaria", "confeitaria", "lanchonete",
        "bar", "cafe", "café", "pastelaria", "salgados", "churrascaria", "hamburgueria", "sorveteria",
        "bacio di latte", "carmelita", "bistrô", "bistro", "espetinho"
    ],
    "Combustível": [
        "posto", "shell", "ipiranga", "petrobras", "br distribuidora", "ale", "auto posto",
        "abastece", "gasolina", "combustivel", "combustível", "graal", "rede de postos"
    ],
    "Transporte": [
        "uber", "99app", "99 tecnologia", "99 pop", "taxi", "táxi", "estapar", "sem parar",
        "conectcar", "veloe", "estacionamento", "pedagio", "pedágio", "movida", "localiza", "unidas"
    ],
    "Compras": [
        "amazon", "mercado livre", "mercadolivre", "shopee", "magalu", "magazine luiza", "americanas",
        "casas bahia", "shein", "aliexpress", "zara", "riachuelo", "renner", "c&a", "kalunga",
        "leroy merlin", "telhanorte", "centauro", "decathlon", "kabum", "pichau", "terabyte", "jim.com"
    ],
    "Assinaturas": [
        "vindi", "quindim", "netflix", "spotify", "disney", "disney+", "hbo", "max", "prime video",
        "apple.com/bill", "google", "microsoft", "youtube", "deezer", "globo play", "globoplay",
        "chatgpt", "openai", "claude", "github", "coursera", "udemy"
    ],
    "Saúde": [
        "drogasil", "droga raia", "drogarias pacheco", "pague menos", "panvel", "drogaria sao paulo",
        "drogaria são paulo", "farmacia", "farmácia", "drogaria", "clinica", "clínica", "laboratorio",
        "laboratório", "unimed", "fleury", "dasa", "lavoisier", "hospital", "dentista", "odontologia"
    ],
    "Tarifas e Juros": [
        "iof", "interest", "juros", "parcele facil", "parcele fácil", "anuidade", "tarifa", "multa",
        "encargos", "stmt instalment", "balance iof"
    ]
}

# Snippet scoring for SearXNG fallback
SEARXNG_KEYWORD_MAP = {
    "Alimentação": ["restaurante", "salgados", "lanchonete", "comida", "padaria", "confeitaria", "lanches", "delivery", "buffet", "gastronomia"],
    "Supermercado": ["supermercado", "hipermercado", "mercearia", "atacadista", "clube de compras", "alimentos", "varejo de alimentos"],
    "Combustível": ["posto de combustiveis", "gasolina", "etanol", "diesel", "abastecimento", "combustivel", "postos"],
    "Transporte": ["transporte", "mobilidade", "passageiros", "estacionamento", "pedagio", "locadora de veiculos"],
    "Compras": ["loja", "e-commerce", "roupas", "calcados", "artigos", "varejo", "eletronicos", "comercio varejista"],
    "Assinaturas": ["assinatura", "software", "saas", "streaming", "mensalidade", "plataforma online", "servicos digitais"],
    "Saúde": ["farmacia", "drogaria", "medicamentos", "medico", "clinica", "hospital", "saude", "odontologia"],
}


async def search_searxng(query: str) -> tuple[str | None, float]:
    """Fallback classifier querying local SearXNG instance."""
    clean_q = re.sub(r"[\*#\-_/]", " ", query)
    clean_q = re.sub(r"\s+", " ", clean_q).strip()
    clean_q = f'"{clean_q}" brasil'
    
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.get(
                f"{SEARXNG_URL}/search",
                params={"q": clean_q, "format": "json", "language": "pt-BR"}
            )
            if res.status_code == 200:
                data = res.json()
                results = data.get("results", [])
                snippets = [r.get("title", "") + " " + r.get("content", "") for r in results[:5]]
                full_text = normalize(" ".join(snippets))
                
                category_scores: dict[str, int] = {}
                for cat, keywords in SEARXNG_KEYWORD_MAP.items():
                    score = sum(1 for kw in keywords if normalize(kw) in full_text)
                    if score > 0:
                        category_scores[cat] = score
                
                if category_scores:
                    best_cat = max(category_scores, key=category_scores.get)
                    confidence = min(0.85, 0.5 + 0.1 * category_scores[best_cat])
                    return best_cat, confidence
    except Exception:
        pass
    return None, 0.0


async def classify_merchant(ctx: Any, description: str) -> dict[str, Any]:
    """
    Multi-tier local classifier:
    1. Built-in Deterministic Dictionary (Fastest, 100% offline)
    2. Household Database Category Rules (`category_rules`)
    3. Local SearXNG Web Enrichment (Local Fallback)
    4. Default fallback ("Outros")
    """
    desc_norm = normalize(description)
    
    # 1. Deterministic Known Patterns
    for category_name, patterns in KNOWN_MERCHANT_PATTERNS.items():
        for pat in patterns:
            pat_norm = normalize(pat)
            if re.search(r"(?<!\w)" + re.escape(pat_norm) + r"(?!\w)", desc_norm):
                return {
                    "category_name": category_name,
                    "category_id": None,
                    "confidence": 0.98,
                    "source": "known_brand_rule"
                }

    # 2. Database Category Rules
    if ctx and hasattr(ctx, "conn"):
        try:
            db_categories = {c["id"]: c["name"] for c in await rows(ctx, "categories")}
            for rule in await rows(ctx, "category_rules"):
                if not rule["enabled"] or rule["category_id"] not in db_categories:
                    continue
                rule_pat = normalize(rule["pattern"])
                matched = (desc_norm == rule_pat) if rule["match_type"] == "EXACT" else (rule_pat in desc_norm)
                if matched:
                    return {
                        "category_name": db_categories[rule["category_id"]],
                        "category_id": str(rule["category_id"]),
                        "confidence": float(rule["confidence"] or 0.95),
                        "source": "db_category_rule"
                    }
        except Exception:
            pass

    # 3. SearXNG Fallback Enrichment
    searx_cat, confidence = await search_searxng(description)
    if searx_cat:
        return {
            "category_name": searx_cat,
            "category_id": None,
            "confidence": confidence,
            "source": "local_searxng"
        }

    # 4. Default Fallback
    return {
        "category_name": "Outros",
        "category_id": None,
        "confidence": 0.3,
        "source": "default"
    }
