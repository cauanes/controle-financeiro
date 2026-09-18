import re
from typing import Any

import httpx

from app.core.config import settings
from app.core.db import rows
from app.modules.resources import normalize

# 1. Deterministic Known Merchants / Brands Dictionary (100% offline & fast)
KNOWN_MERCHANT_PATTERNS: dict[str, list[str]] = {
    "Supermercado": [
        "sams club", "sam's club", "carrefour", "pao de acucar", "pão de açúcar", "extra", "assai", "assaí",
        "atacadao", "atacadão", "zaffari", "dia", "muffato", "angeloni", "big", "condor", "supermercado",
        "mercado", "hortifruti", "sacolao", "sacolão", "mambo", "st marche", "natural da terra", "crf"
    ],
    "Alimentação": [
        "happy salgados", "mcdonalds", "mc donald", "burger king", "bk", "ifood", "ifd", "rappi", "subway",
        "outback", "starbucks", "restaurante", "pizzaria", "pizza", "padaria", "confeitaria", "lanchonete",
        "bar", "cafe", "café", "pastelaria", "salgados", "churrascaria", "hamburgueria", "sorveteria",
        "bacio di latte", "carmelita", "bistrô", "bistro", "espetinho", "recanto"
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
    "Supermercado": [
        "supermercado", "hipermercado", "mercearia", "atacadista", "clube de compras",
        "mercadorias em geral", "varejo de alimentos", "assai", "atacadao", "hortifruti",
        "varejista de mercadorias", "distribuidora de alimentos", "alimentos e bebidas"
    ],
    "Alimentação": [
        "restaurante", "salgados", "lanchonete", "comida", "padaria", "confeitaria",
        "lanches", "delivery", "buffet", "gastronomia", "refeicoes", "mcdonald", "fast food",
        "bar", "cafe", "cafeteria", "hamburguer", "churrascaria", "pizzaria", "alimenticios", "alimentos"
    ],
    "Combustível": [
        "posto de combustiveis", "gasolina", "etanol", "diesel", "abastecimento", "combustivel",
        "combustíveis", "postos", "carburante", "lubrificantes", "petroleo", "raizen", "ipiranga", "vibra"
    ],
    "Transporte": [
        "transporte", "mobilidade", "passageiros", "estacionamento", "pedagio", "locadora de veiculos",
        "locacao de automoveis", "uber", "taxi", "táxi", "99", "concessionaria de rodovias", "rodovias",
        "linha aerea", "passagens", "logistica"
    ],
    "Compras": [
        "loja", "e-commerce", "roupas", "calcados", "artigos", "varejo", "eletronicos",
        "comercio varejista", "departamento", "magazine", "vestuario", "utilidades", "papelaria", "livraria"
    ],
    "Assinaturas": [
        "assinatura", "software", "saas", "streaming", "mensalidade", "plataforma online",
        "servicos digitais", "processamento de dados", "tecnologia da informacao", "hospedagem"
    ],
    "Saúde": [
        "farmacia", "drogaria", "medicamentos", "medico", "clinica", "hospital", "saude",
        "odontologia", "consultorio", "laboratorio", "exames", "plano de saude", "medicamento", "terapia"
    ],
    "Educação": [
        "escola", "colegio", "universidade", "faculdade", "curso", "educacao", "ensino",
        "treinamento", "idiomas", "educacional"
    ],
    "Moradia": [
        "energia eletrica", "saneamento", "agua e esgoto", "gas encanado", "condominio",
        "imobiliaria", "aluguel", "eletricidade"
    ],
    "Lazer": [
        "cinema", "teatro", "show", "eventos", "ingressos", "parque", "viagem", "hotel",
        "pousada", "turismo"
    ],
}

CORPORATE_ENTITY_MARKERS = (
    "LTDA", "S.A.", "S/A", "EIRELI", "ME", "EPP", "DISTRIBUIDORA", "COMERCIO",
    "PARTICIPACOES", "PAGAMENTOS", "SERVICOS", "EMPREENDIMENTOS", "INDUSTRIA",
    "ALIMENTOS", "LOGISTICA", "TRANSPORTES", "AUTO POSTO", "DROGARIA", "FARMACIA"
)


async def query_searxng(query_str: str, count: int = 5) -> list[dict]:
    """Helper to query local SearXNG with fallback host resolution."""
    if not settings.searxng_url:
        return []
    urls = [settings.searxng_url]
    if "host.docker.internal" in settings.searxng_url:
        urls.append(settings.searxng_url.replace("host.docker.internal", "localhost"))
        urls.append(settings.searxng_url.replace("host.docker.internal", "127.0.0.1"))
    elif "localhost" in settings.searxng_url:
        urls.append(settings.searxng_url.replace("localhost", "host.docker.internal"))

    for base_url in urls:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.get(
                    f"{base_url.rstrip('/')}/search",
                    params={"q": query_str, "format": "json", "language": "pt-BR"},
                )
                if res.status_code == 200:
                    data = res.json()
                    return data.get("results", [])[:count]
        except Exception:
            continue
    return []


async def search_searxng(query: str) -> tuple[str | None, float]:
    """Fallback classifier querying local SearXNG instance with corporate entity and CNPJ enrichment."""
    clean_q = re.sub(r"[\*#\-_/]", " ", query)
    clean_q = re.sub(r"\s+", " ", clean_q).strip()
    if not clean_q:
        return None, 0.0

    cnpj_match = re.search(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)|\b\d{14}\b", query)
    upper_query = query.upper()
    is_corporate = bool(cnpj_match) or any(marker in upper_query for marker in CORPORATE_ENTITY_MARKERS)

    if cnpj_match:
        cnpj_digits = re.sub(r"\D", "", cnpj_match.group(0))
        search_query = f'"{cnpj_digits}" razao social nome fantasia brasil'
    elif is_corporate:
        search_query = f'"{clean_q}" razao social nome fantasia atividade brasil'
    else:
        search_query = f'"{clean_q}" atividade comercio servico brasil'

    try:
        results = await query_searxng(search_query, count=5)
        if not results:
            return None, 0.0

        snippets = [r.get("title", "") + " " + r.get("content", "") for r in results]
        full_text = normalize(" ".join(snippets))

        # Check if any known brand pattern appears in the search snippet results
        for category_name, patterns in KNOWN_MERCHANT_PATTERNS.items():
            for pat in patterns:
                pat_norm = normalize(pat)
                if re.search(r"(?<!\w)" + re.escape(pat_norm) + r"(?!\w)", full_text):
                    return category_name, 0.85

        # Score categories based on domain keywords in search snippets
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
    1. Household Database Category Rules (`category_rules`), including CNPJ
    2. Built-in Deterministic Dictionary (Fastest, 100% offline)
    3. Local SearXNG Web Enrichment (Local Fallback)
    4. Default fallback ("Outros")
    """
    desc_norm = normalize(description)
    
    # A family rule must take precedence over a generic brand guess. CNPJ
    # punctuation is irrelevant, but a partial number must never match.
    if ctx and hasattr(ctx, "conn"):
        try:
            db_categories = {
                c["id"]: c["name"] for c in await rows(ctx, "categories")
                if c["kind"] == "EXPENSE" and not c["archived_at"]
            }
            cnpj_candidates = {
                re.sub(r"\D", "", match.group(0))
                for match in re.finditer(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)", description)
            }
            rules = sorted(await rows(ctx, "category_rules"), key=lambda r: r["priority"], reverse=True)
            for rule in rules:
                if (not rule["enabled"] or rule["category_id"] not in db_categories
                    or rule["user_id"] not in (None, getattr(ctx, "user_id", None))):
                    continue
                rule_pat = normalize(rule["pattern"])
                cnpj_digits = re.sub(r"\D", "", rule["pattern"])
                if len(cnpj_digits) == 14:
                    matched = cnpj_digits in cnpj_candidates
                else:
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

    # Generic merchant names are suggestions only; the user sees them before import.
    for category_name, patterns in KNOWN_MERCHANT_PATTERNS.items():
        for pat in patterns:
            pat_norm = normalize(pat)
            if re.search(r"(?<!\w)" + re.escape(pat_norm) + r"(?!\w)", desc_norm):
                return {"category_name": category_name, "category_id": None,
                        "confidence": 0.8, "source": "known_brand_rule"}

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
