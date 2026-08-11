from enum import StrEnum


class TransactionType(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"


class CategoryKind(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"


class AccountKind(StrEnum):
    CASH = "cash"
    CARD = "card"
    SAVINGS = "savings"
    OTHER = "other"


class TxSource(StrEnum):
    """Откуда приехала запись. Нужна для идемпотентности импорта и для отладки синка."""

    APP = "app"
    BOT = "bot"
    SHEET = "sheet"
    IMPORT = "import"


class OutboxOp(StrEnum):
    UPSERT = "upsert"
    DELETE = "delete"
