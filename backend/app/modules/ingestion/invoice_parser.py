import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12
}


@dataclass
class CardInfo:
    type: str = "titular"  # titular | virtual | adicional
    last4: str = ""
    holder: str = ""


@dataclass
class InvoiceTransaction:
    date: str | None = None  # YYYY-MM-DD
    description: str = ""
    amount: float = 0.0
    type: str = "EXPENSE"  # EXPENSE | INSTALLMENT_EXPENSE | PAYMENT_OR_CREDIT | FEE_OR_TAX
    installment_current: int | None = None
    installment_total: int | None = None
    card: CardInfo | None = None
    category: str | None = None
    category_id: str | None = None


@dataclass
class InvoiceSummary:
    total_amount: float | None = None
    due_date: str | None = None  # YYYY-MM-DD
    closing_date: str | None = None  # YYYY-MM-DD
    available_limit: float | None = None
    total_limit: float | None = None
    paid_amount: float | None = None
    issuer: str | None = None


@dataclass
class InvoiceResult:
    summary: InvoiceSummary = field(default_factory=InvoiceSummary)
    transactions: list[InvoiceTransaction] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": asdict(self.summary),
            "transactions": [
                {
                    **asdict(t),
                    "card": asdict(t.card) if t.card else None
                }
                for t in self.transactions
            ],
            "raw_text": self.raw_text
        }


def parse_money(val_str: str | None) -> float | None:
    if not val_str:
        return None
    clean = re.sub(r"[^\d,\.]", "", val_str)
    # OCR often drops the decimal separator ("252773" for "252,73").
    # Never guess cents when the result may become a financial transaction.
    if not re.fullmatch(r"(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}|\d+\.\d{2}", clean):
        return None
    if "," in clean and "." in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif "," in clean:
        clean = clean.replace(",", ".")
    try:
        val = float(clean)
        return val if val > 0 else None
    except ValueError:
        return None


def detect_issuer(text: str) -> str | None:
    text_lower = text.lower()
    if "banco csf" in text_lower or "sams club" in text_lower or "sam's club" in text_lower:
        return "Sam's Club (Banco CSF / Carrefour)"
    if "nubank" in text_lower or "nu pagamentos" in text_lower:
        return "Nubank"
    if "itaú" in text_lower or "itau" in text_lower:
        return "Itaú"
    if "bradesco" in text_lower:
        return "Bradesco"
    if "santander" in text_lower:
        return "Santander"
    if re.search(r"\bbanco inter\b|\binter bank\b", text_lower):
        return "Banco Inter"
    if "c6" in text_lower or "c6 bank" in text_lower:
        return "C6 Bank"
    if "banco do brasil" in text_lower:
        return "Banco do Brasil"
    if re.search(r"\bcaixa\b|\bcef\b|\bcartoes caixa\b|\bcartões caixa\b", text_lower):
        return "Caixa Econômica"
    return None


def extract_invoice_installment(text: str) -> tuple[int, int] | None:
    # 1. "parcela 02/10", "parcela 2 de 10", "parc 2/10", "parc. 02/10", "parc 02 de 10"
    m = re.search(r"\b(?:parcelas?|parc\.?)\s*(\d{1,2})\s*(?:[/]|de|\s+de\s+)\s*(\d{1,2})\b", text, re.I)
    if m:
        c, t = int(m.group(1)), int(m.group(2))
        if 1 <= c <= t <= 120:
            return c, t
    # 2. "(02/10)", "(2/10)", "(02 de 10)"
    m = re.search(r"\(\s*(\d{1,2})\s*(?:[/]|de|\s+de\s+)\s*(\d{1,2})\s*\)", text, re.I)
    if m:
        c, t = int(m.group(1)), int(m.group(2))
        if 1 <= c <= t <= 120:
            return c, t
    # 3. Trailing " 02/10" or " 2/10"
    m = re.search(r"\s+(\d{1,2})/(\d{1,2})\s*$", text)
    if m:
        c, t = int(m.group(1)), int(m.group(2))
        if 1 <= c <= t <= 120:
            return c, t
    return None


def parse_invoice(text: str, default_year: int | None = None) -> InvoiceResult:
    if default_year is None:
        default_year = datetime.now().year

    lines = [re.sub(r"[\s>»—]+$", "", line).strip() for line in text.splitlines() if line.strip()]
    summary = InvoiceSummary(issuer=detect_issuer(text))
    
    # 1. Parse Summary & Header Fields
    for i, line in enumerate(lines):
        # Total da fatura
        if re.search(
            r"\b(valor total|total da fatura|total atual|fatura fechada|valor atual|total desta fatura|fatura aberta|total nacional)\b",
            line,
            re.I,
        ):
            search_block = " ".join(lines[max(0, i - 1) : min(len(lines), i + 4)])
            m = re.search(r"(?:R\$|RS|R\s*\$|\$)\s*([\d\.,]+)", search_block, re.I)
            if m and not summary.total_amount:
                summary.total_amount = parse_money(m.group(1))

        # Vencimento
        m_venc = re.search(
            r"\b(?:vence\s+em|vencimento|vence\s*:\s*)\s*[:\s]*(\d{1,2})[/\.](\d{1,2})(?:[/\.](\d{2,4}))?",
            line,
            re.I,
        )
        if not m_venc:
            m_venc_txt = re.search(r"(\d{1,2})\s+de\s+([a-zA-Zç]+)(?:\s+de\s+(\d{4}))?", line, re.I)
            if m_venc_txt and ("vence" in line.lower() or "vencimento" in line.lower()):
                day = int(m_venc_txt.group(1))
                mn = m_venc_txt.group(2).lower()
                if mn in MONTHS:
                    m_num = MONTHS[mn]
                    yr = int(m_venc_txt.group(3)) if m_venc_txt.group(3) else default_year
                    summary.due_date = f"{yr:04d}-{m_num:02d}-{day:02d}"
        else:
            d, m_num = int(m_venc.group(1)), int(m_venc.group(2))
            yr = int(m_venc.group(3)) if m_venc.group(3) else default_year
            summary.due_date = f"{yr:04d}-{m_num:02d}-{d:02d}"

        # Fechamento / Melhor dia / Melhor data de compra
        m_fech = re.search(
            r"\b(?:fecha\s+em|fechamento|melhor dia|melhor data(?:\s+de\s+compra)?)\s*[:\.\s]*(\d{1,2})[/\.](\d{1,2})(?:[/\.](\d{2,4}))?",
            line,
            re.I,
        )
        if not m_fech:
            m_fech_txt = re.search(r"(\d{1,2})\s+de\s+([a-zA-Zç]+)(?:\s+de\s+(\d{4}))?", line, re.I)
            if m_fech_txt and ("fecha" in line.lower() or "fechamento" in line.lower()):
                day = int(m_fech_txt.group(1))
                mn = m_fech_txt.group(2).lower()
                if mn in MONTHS:
                    m_num = MONTHS[mn]
                    yr = int(m_fech_txt.group(3)) if m_fech_txt.group(3) else default_year
                    summary.closing_date = f"{yr:04d}-{m_num:02d}-{day:02d}"
        else:
            d, m_num = int(m_fech.group(1)), int(m_fech.group(2))
            yr = int(m_fech.group(3)) if m_fech.group(3) else default_year
            summary.closing_date = f"{yr:04d}-{m_num:02d}-{d:02d}"

        # Limite Disponível
        if "disponivel" in line.lower() or "disponível" in line.lower():
            search_block = " ".join(lines[i : min(len(lines), i + 3)])
            m = re.search(r"(?:R\$|RS|R\s*\$|\$)\s*([\d\.,]+)", search_block, re.I)
            if m and not summary.available_limit:
                summary.available_limit = parse_money(m.group(1))

        # Limite Total
        if (
            "limite total" in line.lower()
            or "limite de crédito" in line.lower()
            or "limite do cartão" in line.lower()
        ):
            search_block = " ".join(lines[i : min(len(lines), i + 3)])
            m = re.search(r"(?:R\$|RS|R\s*\$|\$)\s*([\d\.,]+)", search_block, re.I)
            if m and not summary.total_limit:
                summary.total_limit = parse_money(m.group(1))

        # Valor Pago / Créditos
        if any(
            k in line.lower()
            for k in [
                "valor pago",
                "créditos",
                "crédito total",
                "pagamento efetuado",
                "pagamento recebido",
            ]
        ):
            m = re.search(r"(?:R\$|RS|R\s*\$|\$)\s*([\d\.,]+)", line, re.I)
            if m and not summary.paid_amount:
                summary.paid_amount = parse_money(m.group(1))

    # 2. Parse Detailed Transactions
    raw_transactions: list[InvoiceTransaction] = []
    current_date: str | None = None
    current_card: CardInfo | None = None

    date_regex = re.compile(
        r"(?:(?:segunda|terça|terca|quarta|quinta|sexta|sábado|sabado|domingo)(?:-feira)?,?\s*)?(\d{1,2})\s+de\s+([a-zA-Zç]+)(?:\s+de\s+(\d{4}))?",
        re.I,
    )
    short_date_regex = re.compile(r"^(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?$")

    card_regex = re.compile(
        r"(?:cart[aã]o\s+(?:titular|virtual|adicional)?\s*(?:final\s*)?|final\s*[:\s]*)(\d{4})?\s*([A-Za-z\s\.\-]+)?",
        re.I,
    )

    item_regex = re.compile(
        r"^([\w\*\.,\s_/&@#'’\-]{2,80}?)\s+(?:(?:-|—|\+)\s*)?(?:R\$|RS|R\s*\$|\$)\s*([\d\.,]+)$",
        re.I,
    )

    for idx, line in enumerate(lines):
        # Check Date Header
        m_date = date_regex.search(line)
        if m_date and "vencimento" not in line.lower() and "vence" not in line.lower():
            day = int(m_date.group(1))
            mn = m_date.group(2).lower()
            if mn in MONTHS:
                m_num = MONTHS[mn]
                yr = int(m_date.group(3)) if m_date.group(3) else default_year
                current_date = f"{yr:04d}-{m_num:02d}-{day:02d}"
                continue

        m_sdate = short_date_regex.match(line)
        if m_sdate:
            d, m_num = int(m_sdate.group(1)), int(m_sdate.group(2))
            yr = int(m_sdate.group(3)) if m_sdate.group(3) else default_year
            current_date = f"{yr:04d}-{m_num:02d}-{d:02d}"
            continue

        # Check Card Info Header
        m_card = card_regex.search(line)
        if m_card and (m_card.group(1) or m_card.group(2)):
            card_last4 = m_card.group(1) or ""
            card_holder = (m_card.group(2) or "").strip(" -—.,")
            card_type = "titular"
            if "virtual" in line.lower():
                card_type = "virtual"
            elif "adicional" in line.lower():
                card_type = "adicional"
            if card_last4 or card_holder:
                current_card = CardInfo(type=card_type, last4=card_last4, holder=card_holder)
            continue

        # OCR of mobile screenshots frequently puts the merchant and amount on
        # separate lines. Only pair them when the previous line looks like a
        # merchant, never with a date, card label or invoice summary.
        m_item = item_regex.match(line)
        amount_only = re.search(r"^(?:R\$|RS|R\s*\$|\$)\s*([\d\.,]+)$", line, re.I)
        previous = lines[idx - 1] if idx else ""
        is_pure_date = bool(date_regex.fullmatch(previous) or short_date_regex.fullmatch(previous))
        is_summary_word = bool(
            re.search(
                r"\b(valor total|valor atual|total da fatura|total atual|fatura|limite|dispon[ií]vel|umite|vencimento|melhor dia|dolar do dia|historico de compras)\b",
                previous,
                re.I,
            )
        )
        separate_item = (
            bool(amount_only)
            and bool(previous)
            and not is_summary_word
            and not is_pure_date
            and len(previous) >= 3
        )
        if m_item or separate_item:
            desc = (m_item.group(1) if m_item else previous).strip()
            raw_amt = m_item.group(2) if m_item else amount_only.group(1)
            amount = parse_money(raw_amt)
            if amount is None or amount == 0:
                continue

            desc_clean = desc.strip(" -—.,")
            desc_l = desc_clean.lower()
            clean_token = re.sub(r"[^a-z]", "", desc_l)
            if any(
                k in clean_token
                for k in (
                    "valortotal",
                    "valoratual",
                    "totalatual",
                    "totaldafatura",
                    "lancamentosdomes",
                    "disponivel",
                    "limitetotal",
                    "limitedisponivel",
                    "melhordiadecompra",
                    "vencimento",
                    "saldoanterior",
                    "movimentacaonacional",
                    "movimentacaointernacional",
                    "movimentagaonacional",
                    "movimentagaointernacional",
                    "totalnacional",
                    "totalinternacional",
                    "historicodecompras",
                    "faturaaberta",
                    "faturafechada",
                )
            ) or any(
                skip in desc_l
                for skip in [
                    "valor total",
                    "valor atual",
                    "total atual",
                    "total da fatura",
                    "lançamentos do mês",
                    "disponível",
                    "limite total",
                    "limite disponível",
                    "melhor dia de compra",
                    "vencimento",
                    "saldo anterior",
                    "movimentação",
                    "movimentacao",
                    "movimentagao",
                    "total nacional",
                    "total internacional",
                ]
            ):
                continue

            item_date = current_date
            m_start_date = re.match(r"^(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?\s+(.*)$", desc_clean)
            if m_start_date:
                d_val, m_val = int(m_start_date.group(1)), int(m_start_date.group(2))
                y_val = int(m_start_date.group(3)) if m_start_date.group(3) else default_year
                item_date = f"{y_val:04d}-{m_val:02d}-{d_val:02d}"
                desc_clean = m_start_date.group(4).strip(" -—.,")
                desc_l = desc_clean.lower()
            else:
                m_end_date = re.match(r"^(.*?)\s+(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?$", desc_clean)
                if m_end_date:
                    d_val, m_val = int(m_end_date.group(2)), int(m_end_date.group(3))
                    y_val = int(m_end_date.group(4)) if m_end_date.group(4) else default_year
                    item_date = f"{y_val:04d}-{m_val:02d}-{d_val:02d}"
                    desc_clean = m_end_date.group(1).strip(" -—.,")
                    desc_l = desc_clean.lower()

            inst_curr, inst_total = None, None
            item_card = current_card

            # Check installment directly in line
            inst_match = extract_invoice_installment(desc_clean)
            if inst_match:
                inst_curr, inst_total = inst_match

            # Look ahead next 2 lines for installment details only (stop if next line is another item/header)
            for next_line in lines[idx + 1 : min(len(lines), idx + 3)]:
                if (
                    item_regex.match(next_line)
                    or date_regex.search(next_line)
                    or card_regex.search(next_line)
                ):
                    break
                next_inst = extract_invoice_installment(next_line)
                if next_inst and not inst_curr:
                    inst_curr, inst_total = next_inst

            # Determine transaction category/type
            tx_type = "EXPENSE"
            if any(k in desc_l for k in ["pagamento", "crédito", "credito", "estorno", "desconto"]):
                tx_type = "PAYMENT_OR_CREDIT"
            elif any(
                k in desc_l
                for k in ["iof", "interest", "juros", "tarifa", "anuidade", "multa", "encargos"]
            ):
                tx_type = "FEE_OR_TAX"
            elif inst_total and inst_total > 1:
                tx_type = "INSTALLMENT_EXPENSE"

            raw_transactions.append(
                InvoiceTransaction(
                    date=item_date,
                    description=desc_clean,
                    amount=amount,
                    type=tx_type,
                    installment_current=inst_curr,
                    installment_total=inst_total,
                    card=item_card,
                )
            )

    # 3. Deduplicate across overlapping screenshot crops
    deduped = deduplicate_transactions(raw_transactions)
    return InvoiceResult(summary=summary, transactions=deduped, raw_text=text)


def deduplicate_transactions(transactions: list[InvoiceTransaction]) -> list[InvoiceTransaction]:
    unique: list[InvoiceTransaction] = []
    seen: set[str] = set()

    for tx in transactions:
        # Create a signature for deduplication
        clean_desc = re.sub(r"[\s\*\.,\-_/]", "", tx.description.lower())
        sig = f"{tx.date}_{clean_desc}_{tx.amount:.2f}_{tx.installment_current}_{tx.installment_total}"
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(tx)

    return unique
