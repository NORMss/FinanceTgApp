"""DTO для HTTP-слоя.

Суммы ходят по API двумя способами:
  * наружу — `amount_minor` (целое в копейках), форматирует клиент;
  * внутрь — `amount` строкой («1 234,56»), разбирает сервер через Decimal.
Так на клиенте не появляется ни одного float, и «1234.56» не превращается в 1234.5599999.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import AccountKind, CategoryKind, TransactionType, TxSource


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ---


class LoginRequest(BaseModel):
    init_data: str = ""


class UserOut(ORMModel):
    id: str
    telegram_id: int
    display_name: str
    username: str | None = None


class LoginResponse(BaseModel):
    token: str
    expires_at: int
    user: UserOut
    base_currency: str


# --- справочники ---


class AccountOut(ORMModel):
    id: str
    name: str
    kind: AccountKind
    currency: str
    is_shared: bool
    owner_id: str | None = None
    archived: bool
    sort: int


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: AccountKind = AccountKind.CARD
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    is_shared: bool = False
    owner_id: str | None = None
    opening_balance: str = "0"


class CategoryOut(ORMModel):
    id: str
    name: str
    kind: CategoryKind
    icon: str
    parent_id: str | None = None
    archived: bool
    sort: int


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: CategoryKind = CategoryKind.EXPENSE
    icon: str = ""
    parent_id: str | None = None
    sort: int = 100


# --- операции ---


class SplitOut(BaseModel):
    user_id: str
    share_minor: int


class TransactionOut(ORMModel):
    id: str
    occurred_at: datetime
    type: TransactionType
    amount_minor: int
    currency: str
    account_id: str
    counter_account_id: str | None = None
    category_id: str | None = None
    author_id: str
    note: str
    tags: str
    source: TxSource
    splits: list[SplitOut] = Field(default_factory=list)


class TransactionCreate(BaseModel):
    type: TransactionType = TransactionType.EXPENSE
    amount: str
    account_id: str | None = None
    counter_account_id: str | None = None
    category_id: str | None = None
    occurred_at: datetime | None = None
    note: str = ""
    tags: str = ""
    # auto — трата с общего счёта делится поровну; none — не делить
    split_mode: Literal["auto", "none"] = "auto"
    splits: dict[str, str] | None = None


class TransactionUpdate(BaseModel):
    amount: str | None = None
    account_id: str | None = None
    category_id: str | None = None
    occurred_at: datetime | None = None
    note: str | None = None
    tags: str | None = None


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int


# --- отчёты ---


class CategoryTotalOut(BaseModel):
    category_id: str | None
    name: str
    icon: str
    amount_minor: int
    count: int
    share: float


class AuthorTotalOut(BaseModel):
    user_id: str
    name: str
    amount_minor: int


class SummaryOut(BaseModel):
    period_start: datetime
    period_end: datetime
    income_minor: int
    expense_minor: int
    net_minor: int
    count: int
    by_category: list[CategoryTotalOut]
    by_author: list[AuthorTotalOut]


class AccountBalanceOut(BaseModel):
    account_id: str
    name: str
    currency: str
    is_shared: bool
    balance_minor: int


class BalancesOut(BaseModel):
    accounts: list[AccountBalanceOut]
    total_minor: int


class UserBalanceOut(BaseModel):
    user_id: str
    name: str
    paid_minor: int
    owed_minor: int
    net_minor: int


class SettleOut(BaseModel):
    users: list[UserBalanceOut]
    hint: str


class SyncStatusOut(BaseModel):
    enabled: bool
    configured: bool
    pending: int
    last_push_at: datetime | None = None
    last_error: str | None = None
    spreadsheet_url: str | None = None
