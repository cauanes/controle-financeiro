from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.core.money import money

Money = Annotated[Decimal, BeforeValidator(money)]
PositiveMoney = Annotated[Decimal, BeforeValidator(lambda value: money(value, positive=True))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Account(Strict):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["CHECKING", "SAVINGS", "CASH", "INVESTMENT"] = "CHECKING"
    currency: Literal["BRL"] = "BRL"
    opening_balance: Money = Decimal("0.00")
    opening_balance_date: date
    is_emergency_reserve: bool = False


class Category(Strict):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["EXPENSE", "INCOME"] = "EXPENSE"
    parent_id: UUID | None = None
    is_essential: bool | None = None


class Merchant(Strict):
    name: str = Field(min_length=1, max_length=200)


class Card(Strict):
    name: str = Field(min_length=1, max_length=100)
    issuer: str | None = None
    closing_day: int = Field(ge=1, le=31)
    due_day: int = Field(ge=1, le=31)
    limit_amount: Money | None = None
    default_payment_account_id: UUID | None = None


class Source(Strict):
    kind: Literal["ACCOUNT", "CREDIT_CARD", "ACCOUNT_TRANSFER", "INVOICE_PAYMENT"]
    id: UUID | None = None
    source_id: UUID | None = None
    destination_id: UUID | None = None
    account_id: UUID | None = None
    invoice_id: UUID | None = None


class Transaction(Strict):
    type: Literal["EXPENSE", "INCOME", "TRANSFER"]
    status: Literal["POSTED", "PLANNED"] = "POSTED"
    amount: PositiveMoney
    currency: Literal["BRL"] = "BRL"
    transaction_date: date
    competence_date: date | None = None
    due_date: date | None = None
    description: str = Field(min_length=1, max_length=500)
    financial_source: Source
    category_id: UUID | None = None
    merchant_id: UUID | None = None
    responsible_user_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    installment_count: int = Field(default=1, ge=1, le=120)


class Patch(Strict):
    expected_version: int = Field(ge=1)
    changes: dict


class Version(Strict):
    expected_version: int = Field(ge=1)


class Rule(Strict):
    pattern: str = Field(min_length=1, max_length=200)
    match_type: Literal["EXACT", "CONTAINS"] = "CONTAINS"
    category_id: UUID
    priority: int = 0
    confidence: Decimal = Field(default=Decimal(".95"), ge=0, le=1)
    user_id: UUID | None = None
    enabled: bool = True


class MerchantRule(Strict):
    pattern: str = Field(min_length=1, max_length=200)
    match_type: Literal["EXACT", "CONTAINS"] = "CONTAINS"
    merchant_id: UUID
    priority: int = 0
    enabled: bool = True


class BudgetLine(Strict):
    category_id: UUID
    amount: Money


class Budget(Strict):
    name: str = Field(min_length=1, max_length=100)
    period_start: date
    period_end: date
    currency: Literal["BRL"] = "BRL"
    categories: list[BudgetLine] = Field(min_length=1, max_length=100)


class Recurring(Strict):
    template: Transaction
    frequency: Literal["MONTHLY", "WEEKLY", "YEARLY"] = "MONTHLY"
    interval_count: int = Field(default=1, ge=1, le=120)
    start_date: date
    end_date: date | None = None
    enabled: bool = True
    cost_class: Literal["FIXED", "VARIABLE", "UNKNOWN"] = "UNKNOWN"


class Goal(Strict):
    name: str = Field(min_length=1, max_length=100)
    target_amount: PositiveMoney
    target_date: date | None = None
    status: Literal["ACTIVE", "COMPLETED", "ARCHIVED"] = "ACTIVE"


class Contribution(Strict):
    amount: PositiveMoney
    contribution_date: date
    transaction_id: UUID | None = None
    direction: Literal["ADD", "WITHDRAW"] = "ADD"


class Asset(Strict):
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(min_length=1, max_length=50)
    valuation: Money
    valuation_date: date
    linked_account_id: UUID | None = None


class Liability(Strict):
    name: str = Field(min_length=1, max_length=100)
    outstanding_amount: Money
    valuation_date: date
    linked_credit_card_id: UUID | None = None
    due_date: date | None = None


class AlertRule(Strict):
    kind: Literal["BUDGET_THRESHOLD", "DUE_SOON", "BUDGET_FORECAST_EXCEEDED", "LOW_PROJECTED_BALANCE"]
    config: dict = Field(default_factory=dict)
    channel: Literal["DASHBOARD", "WHATSAPP"] = "DASHBOARD"
    enabled: bool = True
    quiet_hours: dict = Field(default_factory=lambda: {"start": 22, "end": 8})
    recipient_user_id: UUID
    opt_in: bool = False
