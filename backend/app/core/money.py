import calendar
from datetime import date
from decimal import Decimal, InvalidOperation

from app.core.errors import DomainError


def money(value, *, positive=False):
    if isinstance(value, (float, bool)):
        raise DomainError("Envie dinheiro como string decimal, sem ponto flutuante.")
    try:
        result = Decimal(value)
        if not result.is_finite() or result != result.quantize(Decimal("0.01")) or abs(result) >= 10**16:
            raise ValueError()
        if positive and result <= 0:
            raise ValueError()
        return result.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        raise DomainError("Valor monetário inválido; use até duas casas decimais.") from None


def month_date(year, month, day):
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def add_months(value: date, count: int, anchor=None):
    year, month = divmod(value.year * 12 + value.month - 1 + count, 12)
    return month_date(year, month + 1, anchor or value.day)


def invoice_dates(purchased: date, closing_day: int, due_day: int, offset=0):
    closing = month_date(purchased.year, purchased.month, closing_day)
    if purchased > closing:
        closing = add_months(closing, 1, closing_day)
    closing = add_months(closing, offset, closing_day)
    due = month_date(closing.year, closing.month, due_day)
    if due <= closing:
        due = add_months(due, 1, due_day)
    return closing, due


def installments(total, count):
    if not 1 <= count <= 120:
        raise DomainError("Número de parcelas deve estar entre 1 e 120.")
    cents = int(money(total, positive=True) * 100)
    base, extra = divmod(cents, count)
    if base == 0:
        raise DomainError("Cada parcela deve ter pelo menos um centavo.")
    return [Decimal(base + (i < extra)) / 100 for i in range(count)]
