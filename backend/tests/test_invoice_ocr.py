import glob
from pathlib import Path

import pytest

from app.modules.categorization.merchant_classifier import classify_merchant
from app.modules.ingestion.invoice_parser import InvoiceResult, parse_invoice
from app.modules.ingestion.ocr import extract_text_from_image

SAMPLE_INVOICE_TEXT = """
Sam's Club
Banco CSF S.A.
Valor total da fatura
R$ 2.376,31
Vence em: 12/10/2026
Fecha em: 01/10/2026
Limite disponível: R$ 484,06
Limite total: R$ 12.800,00
Valor pago / créditos: R$ 4.253,61

Quarta-feira, 16 de setembro
Cartão titular final 9728 Carla G.
Vindi *Quindim, SAO PAULO - R$ 60,80
Parcela 1/4

Parcele Fácil - R$ 700,89
Parcela 1/4

Stmt Instalment Additional IOF - R$ 3,09
Parcela 1/4

Interest - R$ 450,85
Parcela 1/4

Quinta-feira, 16 de agosto
JIM.COM* 54397612 BRU,SAO JOS - R$ 750,00
Parcela 2/3

Cartão virtual final 4414 Carla G.
HAPPY SALGADOS, CURITIBA - R$ 252,73
Parcela 2/3

Sábado, 01 de agosto
Cartão titular final 9728 Carla G.
AMAZON BR,SAO PAULO - R$ 34,17
Parcela 2/6

Segunda-feira, 15 de junho
CRF 4857 BGS SAMS CLUB BA - R$ 72,31
Parcela 4/10

Cartão virtual final 4414
CRF 4857 BGS SAMS CLUB BA - R$ 49,98
Parcela 4/4
"""


def test_parse_invoice_header():
    res = parse_invoice(SAMPLE_INVOICE_TEXT, default_year=2026)
    
    assert res.summary.issuer == "Sam's Club (Banco CSF / Carrefour)"
    assert res.summary.total_amount == 2376.31
    assert res.summary.due_date == "2026-10-12"
    assert res.summary.closing_date == "2026-10-01"
    assert res.summary.available_limit == 484.06
    assert res.summary.total_limit == 12800.00
    assert res.summary.paid_amount == 4253.61


def test_parse_invoice_transactions():
    res = parse_invoice(SAMPLE_INVOICE_TEXT, default_year=2026)
    
    assert len(res.transactions) >= 8
    
    # Check Vindi *Quindim
    vindi = next(t for t in res.transactions if "Vindi" in t.description)
    assert vindi.date == "2026-09-16"
    assert vindi.amount == 60.80
    assert vindi.installment_current == 1
    assert vindi.installment_total == 4
    assert vindi.card.last4 == "9728"
    assert vindi.card.type == "titular"
    
    # Check Happy Salgados
    happy = next(t for t in res.transactions if "HAPPY SALGADOS" in t.description)
    assert happy.date == "2026-08-16"
    assert happy.amount == 252.73
    assert happy.installment_current == 2
    assert happy.installment_total == 3
    assert happy.card.last4 == "4414"
    assert happy.card.type == "virtual"
    
    # Check Amazon
    amazon = next(t for t in res.transactions if "AMAZON" in t.description)
    assert amazon.date == "2026-08-01"
    assert amazon.amount == 34.17
    assert amazon.installment_current == 2
    assert amazon.installment_total == 6
    
    # Check Fee / Interest
    interest = next(t for t in res.transactions if "Interest" in t.description)
    assert interest.amount == 450.85
    assert interest.type == "FEE_OR_TAX"


@pytest.mark.asyncio
async def test_merchant_classification_known_rules():
    class DummyCtx:
        conn = None

    ctx = DummyCtx()
    
    c_sams = await classify_merchant(ctx, "CRF 4857 BGS SAMS CLUB BA")
    assert c_sams["category_name"] == "Supermercado"
    
    c_happy = await classify_merchant(ctx, "HAPPY SALGADOS, CURITIBA")
    assert c_happy["category_name"] == "Alimentação"
    
    c_amazon = await classify_merchant(ctx, "AMAZON BR, SAO PAULO")
    assert c_amazon["category_name"] == "Compras"
    
    c_vindi = await classify_merchant(ctx, "Vindi *Quindim")
    assert c_vindi["category_name"] == "Assinaturas"
    
    c_uber = await classify_merchant(ctx, "UBER *TRIP HELP.UBER")
    assert c_uber["category_name"] == "Transporte"
    
    c_gas = await classify_merchant(ctx, "AUTO POSTO SHELL IPIRANGA")
    assert c_gas["category_name"] == "Combustível"
    
    c_iof = await classify_merchant(ctx, "Stmt Instalment Balance IOF")
    assert c_iof["category_name"] == "Tarifas e Juros"


@pytest.mark.asyncio
async def test_household_cnpj_rule_overrides_generic_brand(monkeypatch):
    from app.modules.categorization import merchant_classifier

    class Context:
        conn = object()
        user_id = "family-member"

    async def fake_rows(ctx, table):
        if table == "categories":
            return [{"id": "food", "name": "Alimentação", "kind": "EXPENSE", "archived_at": None}]
        return [{"enabled": True, "category_id": "food", "user_id": None, "priority": 10,
                 "pattern": "12.345.678/0001-90", "match_type": "EXACT", "confidence": 0.95}]

    monkeypatch.setattr(merchant_classifier, "rows", fake_rows)
    result = await classify_merchant(Context(), "SAMS CLUB CNPJ 12345678000190")
    assert result["category_name"] == "Alimentação"
    assert result["source"] == "db_category_rule"


def test_ocr_on_real_invoices():
    img_files = sorted(glob.glob(".local/invoices/*.jpg"))
    if not img_files:
        pytest.skip("Nenhuma imagem em .local/invoices para teste real.")
        
    for img_path in img_files:
        img_bytes = Path(img_path).read_bytes()
        text = extract_text_from_image(img_bytes)
        assert len(text) > 0
        parsed = parse_invoice(text)
        assert isinstance(parsed, InvoiceResult)


def test_merge_classified_transactions():
    from app.workers.runner import (
        build_invoice_header_text,
        build_invoice_question_text,
        invoice_summary_conflict,
        match_credit_card,
        merge_classified_transactions,
    )

    t1 = [
        {"description": "SAMS CLUB", "amount": 128.50, "date": "2026-09-15", "installment_current": 1, "installment_total": 3, "category_name": "Supermercado"},
        {"description": "POSTO IPIRANGA", "amount": 50.00, "date": "2026-09-14", "installment_current": None, "installment_total": None, "category_name": "Combustível"},
    ]
    t2 = [
        {"description": "SAMS CLUB", "amount": 128.50, "date": "2026-09-15", "installment_current": 1, "installment_total": 3, "category_name": "Supermercado"}, # duplicate
        {"description": "UBER *TRIP", "amount": 25.40, "date": "2026-09-13", "installment_current": None, "installment_total": None, "category_name": "Transporte"},
    ]

    merged = merge_classified_transactions(t1, t2)
    assert len(merged) == 3
    assert merged[0]["description"] == "SAMS CLUB"
    assert merged[1]["description"] == "POSTO IPIRANGA"
    assert merged[2]["description"] == "UBER *TRIP"
    assert len(merge_classified_transactions(
        [{"description": "63 Vindi *Quindim", "amount": 60.80, "date": "2026-09-16"}],
        [{"description": "Go Vindi *Quindim", "amount": 60.80, "date": "2026-09-16"}],
    )) == 1
    assert not invoice_summary_conflict({"total_amount": 2376.31}, {"closing_date": "2026-10-01"})
    assert invoice_summary_conflict({"closing_date": "2026-10-01"}, {"closing_date": "2026-11-01"})
    assert invoice_summary_conflict({"total_amount": 2376.31}, {"total_amount": 1800.00})
    family_cards = [
        {"name": "Nubank Cauan 1234", "issuer": "Nubank"},
        {"name": "Nubank Carla 5678", "issuer": "Nubank"},
    ]
    assert match_credit_card(family_cards, "Nubank", set()) == (None, True)
    assert match_credit_card(family_cards, "Nubank", {"5678"}) == (family_cards[1], False)

    summary = {
        "issuer": "Sam's Club",
        "total_amount": 203.90,
        "due_date": "2026-10-10",
        "closing_date": "2026-10-01",
        "available_limit": 5000.0,
        "total_limit": 10000.0,
    }
    q_text = build_invoice_question_text(summary, merged, "Sam's Club")
    assert "Sam's Club" in q_text
    assert "203.90" in q_text
    assert "SAMS CLUB" in q_text
    assert "POSTO IPIRANGA" in q_text
    assert "UBER *TRIP" in q_text
    assert "Apenas os itens listados acima serão importados" in q_text

    h_text = build_invoice_header_text(summary, "Sam's Club")
    assert "Sam's Club" in h_text
    assert "203.90" in h_text
    assert "Ainda não importei nada" in h_text


def test_ocr_lines_do_not_guess_missing_decimal_separator():
    text = """Fatura\nValor atual\nR$ 2.376,31\nQuarta-feira, 16 de setembro
Parcele Fácil\nR$ 700,89\nParcela 1/4\nHAPPY SALGADOS\nR$ 252773
Pagamento de Fatura via PIX\nR$ 1.000,00"""
    result = parse_invoice(text, default_year=2026)
    assert result.summary.total_amount == 2376.31
    assert [(item.description, item.amount) for item in result.transactions if item.type != "PAYMENT_OR_CREDIT"] == [
        ("Parcele Fácil", 700.89)
    ]


def test_parse_caixa_invoice():
    sample_text = """
    Final 4804
    CAIXA ELO GRAFITE INTERN DUAL
    A vencer
    Total da fatura RS 884,12
    Final 4804 - CAUAN ESPLUGUES SILVA
    MOVIMENTAÇÃO NACIONAL R$ 884,12
    03/09 PG PL RECANTO SALTO R$ 209,80
    03/09 IFD 60473794 MAIRCE SI R$ 0,90
    03/09 AUTO POSTO NOSSA SENH R$ 28,50
    04/09 RM CINE PIZZA BODYBUIL R$ 115,50
    04/09 AUTO POSTO NOSSA SENH R$ 318,73
    05/09 Zet R$ 12,50
    06/09 AMAZON BR R$ 67,85
    06/09 KALUNGA COM R$ 60,74
    07/09 BURGER KING R$ 57,70
    07/09 DL GOOGLE Micros R$ 11,90
    TOTAL NACIONAL RS 884,12
    TOTAL INTERNACIONAL RS 0,00
    """
    res = parse_invoice(sample_text, default_year=2026)
    assert res.summary.issuer == "Caixa Econômica"
    assert res.summary.total_amount == 884.12
    assert len(res.transactions) == 10
    assert sum(t.amount for t in res.transactions) == 884.12
    assert res.transactions[0].date == "2026-09-03"
    assert res.transactions[0].description == "PG PL RECANTO SALTO"
    assert res.transactions[0].amount == 209.80
    assert res.transactions[0].card.last4 == "4804"
    assert res.transactions[0].card.holder == "CAUAN ESPLUGUES SILVA"


def test_extract_invoice_installments_various_formats():
    from app.modules.ingestion.invoice_parser import extract_invoice_installment

    assert extract_invoice_installment("LOJA XYZ (02/10)") == (2, 10)
    assert extract_invoice_installment("MERCADO LIVRE (2/10)") == (2, 10)
    assert extract_invoice_installment("MAGAZINELUIZA PARC 03/12") == (3, 12)
    assert extract_invoice_installment("AMAZON BR PARC. 01/05") == (1, 5)
    assert extract_invoice_installment("CASAS BAHIA parcela 4 de 10") == (4, 10)
    assert extract_invoice_installment("FAST SHOP 05/10") == (5, 10)
    assert extract_invoice_installment("UBER TRIP") is None
    assert extract_invoice_installment("PG PL RECANTO SALTO") is None


