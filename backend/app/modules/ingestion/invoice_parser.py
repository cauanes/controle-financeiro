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
    if not clean:
        return None
    if "," in clean and "." in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif "," in clean:
        clean = clean.replace(",", ".")
    elif "." in clean and len(clean.split(".")[-1]) != 2:
        clean = clean.replace(".", "")
    elif len(clean) >= 3 and "." not in clean and "," not in clean:
        clean = clean[:-2] + "." + clean[-2:]
    try:
        val = float(clean)
        return val if val > 0 else None
    except ValueError:
        return None


def detect_issuer(text: str) -> str | None:
    text_lower = text.lower()
    if "sam's club" in text_lower or "sams club" in text_lower or "crf" in text_lower or "banco csf" in text_lower:
        return "Sam's Club (Banco CSF / Carrefour)"
    if "nubank" in text_lower or "nu pagamentos" in text_lower:
        return "Nubank"
    if "itaú" in text_lower or "itau" in text_lower:
        return "Itaú"
    if "bradesco" in text_lower:
        return "Bradesco"
    if "santander" in text_lower:
        return "Santander"
    if "inter" in text_lower or "banco inter" in text_lower:
        return "Banco Inter"
    if "c6" in text_lower or "c6 bank" in text_lower:
        return "C6 Bank"
    if "banco do brasil" in text_lower or "bb" in text_lower:
        return "Banco do Brasil"
    if "caixa" in text_lower or "cef" in text_lower:
        return "Caixa Econômica"
    return None


def parse_invoice(text: str, default_year: int | None = None) -> InvoiceResult:
    if default_year is None:
        default_year = datetime.now().year

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = InvoiceSummary(issuer=detect_issuer(text))
    
    # 1. Parse Summary & Header Fields
    for i, line in enumerate(lines):
        # Total da fatura
        if re.search(r"\b(valor total|total da fatura|total atual|fatura fechada|valor atual|total desta fatura|fatura aberta)\b", line, re.I):
            search_block = " ".join(lines[max(0, i - 1):min(len(lines), i + 4)])
            m = re.search(r"R\$\s*([\d\.,]+)", search_block)
            if m and not summary.total_amount:
                summary.total_amount = parse_money(m.group(1))

        # Vencimento
        m_venc = re.search(r"\b(?:vence\s+em|vencimento|vence\s*:\s*)\s*[:\s]*(\d{1,2})[/\.](\d{1,2})(?:[/\.](\d{2,4}))?", line, re.I)
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

        # Fechamento / Melhor dia
        m_fech = re.search(r"\b(?:fecha\s+em|fechamento|melhor dia)\s*[:\s]*(\d{1,2})[/\.](\d{1,2})(?:[/\.](\d{2,4}))?", line, re.I)
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
            search_block = " ".join(lines[i:min(len(lines), i + 3)])
            m = re.search(r"R\$\s*([\d\.,]+)", search_block)
            if m and not summary.available_limit:
                summary.available_limit = parse_money(m.group(1))

        # Limite Total
        if "limite total" in line.lower() or "limite de crédito" in line.lower() or "limite do cartão" in line.lower():
            search_block = " ".join(lines[i:min(len(lines), i + 3)])
            m = re.search(r"R\$\s*([\d\.,]+)", search_block)
            if m and not summary.total_limit:
                summary.total_limit = parse_money(m.group(1))

        # Valor Pago / Créditos
        if any(k in line.lower() for k in ["valor pago", "créditos", "crédito total", "pagamento efetuado", "pagamento recebido"]):
            m = re.search(r"R\$\s*([\d\.,]+)", line)
            if m and not summary.paid_amount:
                summary.paid_amount = parse_money(m.group(1))

    # 2. Parse Detailed Transactions
    raw_transactions: list[InvoiceTransaction] = []
    current_date: str | None = None
    current_card: CardInfo | None = None

    date_regex = re.compile(
        r"(?:(?:segunda|terça|terca|quarta|quinta|sexta|sábado|sabado|domingo)(?:-feira)?,?\s*)?(\d{1,2})\s+de\s+([a-zA-Zç]+)(?:\s+de\s+(\d{4}))?",
        re.I
    )
    short_date_regex = re.compile(r"^(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?$")

    card_regex = re.compile(
        r"cart[aã]o\s+(titular|virtual|adicional)?\s*(?:final\s*)?(\d{4})?\s*([A-Za-z\s\.]+)?",
        re.I
    )

    item_regex = re.compile(
        r"^([A-Z0-9\*\.,\s\-_/&@#]{2,60}?)\s+(?:(?:-|—|\+)\s*)?R\$\s*([\d\.,]+)$",
        re.I
    )

    installment_regex = re.compile(r"parcela\s*(\d+)\s*[/de\s]+\s*(\d+)", re.I)

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
            card_type = m_card.group(1) or "titular"
            card_last4 = m_card.group(2) or ""
            card_holder = (m_card.group(3) or "").strip()
            current_card = CardInfo(type=card_type.lower(), last4=card_last4, holder=card_holder)
            continue

        # Check Transaction Item
        m_item = item_regex.match(line)
        if m_item:
            desc = m_item.group(1).strip()
            raw_amt = m_item.group(2)
            amount = parse_money(raw_amt)
            if amount is None or amount == 0:
                continue

            desc_clean = desc.strip(" -—.,")
            desc_l = desc_clean.lower()
            if any(skip in desc_l for skip in [
                "valor total", "valor atual", "total atual", "total da fatura",
                "lançamentos do mês", "disponível", "limite total", "limite disponível",
                "melhor dia de compra", "vencimento", "saldo anterior"
            ]):
                continue

            inst_curr, inst_total = None, None
            item_card = current_card

            # Check installment directly in line
            m_self_inst = installment_regex.search(desc_clean)
            if m_self_inst:
                inst_curr = int(m_self_inst.group(1))
                inst_total = int(m_self_inst.group(2))

            # Look ahead next 2 lines for installment details only (stop if next line is another item/header)
            for next_line in lines[idx + 1:min(len(lines), idx + 3)]:
                if item_regex.match(next_line) or date_regex.search(next_line) or card_regex.search(next_line):
                    break
                m_inst = installment_regex.search(next_line)
                if m_inst and not inst_curr:
                    inst_curr = int(m_inst.group(1))
                    inst_total = int(m_inst.group(2))

            # Determine transaction category/type
            tx_type = "EXPENSE"
            if any(k in desc_l for k in ["pagamento", "crédito", "credito", "estorno", "desconto"]):
                tx_type = "PAYMENT_OR_CREDIT"
            elif any(k in desc_l for k in ["iof", "interest", "juros", "tarifa", "anuidade", "multa", "encargos"]):
                tx_type = "FEE_OR_TAX"
            elif inst_total and inst_total > 1:
                tx_type = "INSTALLMENT_EXPENSE"

            raw_transactions.append(
                InvoiceTransaction(
                    date=current_date,
                    description=desc_clean,
                    amount=amount,
                    type=tx_type,
                    installment_current=inst_curr,
                    installment_total=inst_total,
                    card=item_card
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
