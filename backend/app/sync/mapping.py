"""Преобразование операций в строки таблицы и обратно.

Ключевые решения:
  * первая колонка — ULID операции: по ней строится карта «id -> номер строки»;
  * последняя колонка — sync_hash: хеш того, что записало приложение. Если при чтении
    хеш строки не совпадает с сохранённым, значит строку правил человек, и правку надо забрать;
  * ссылки на счета/категории/людей пишем именами, а не id — иначе смысл зеркала теряется.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.models import Transaction, TransactionType
from app.util.money import to_major, to_minor

SHEET_TRANSACTIONS = "transactions"

HEADERS = [
    "id",
    "дата",
    "тип",
    "сумма",
    "валюта",
    "счёт",
    "счёт назначения",
    "категория",
    "кто",
    "заметка",
    "теги",
    "удалено",
    "источник",
    "изменено",
    "sync_hash",
]

# Колонки, которые пользователю разрешено править руками. Всё остальное при обратном
# импорте игнорируется: id и служебные поля меняться не должны.
EDITABLE = ("дата", "сумма", "категория", "заметка", "теги", "удалено")

_TYPE_TO_RU = {
    TransactionType.EXPENSE: "расход",
    TransactionType.INCOME: "доход",
    TransactionType.TRANSFER: "перевод",
}
_RU_TO_TYPE = {value: key for key, value in _TYPE_TO_RU.items()}

DATE_FORMAT = "%Y-%m-%d %H:%M"


@dataclass(slots=True)
class RowView:
    """Разобранная строка таблицы."""

    id: str
    occurred_at: datetime | None
    tx_type: TransactionType | None
    amount_minor: int | None
    category: str
    note: str
    tags: str
    deleted: bool
    sync_hash: str


TRUE_VALUES = {"да", "true", "1", "yes", "x"}


def _canonical(name: str, raw: object) -> str:
    """Приводит ячейку к виду, не зависящему от локали и форматирования таблицы.

    Без этого хеш не сойдётся: приложение пишет 500.0, а Google возвращает «500»
    или «1 234,56» — и каждая строка выглядела бы отредактированной вручную.
    """
    text = str(raw).strip()
    if name == "сумма":
        cleaned = text.replace(" ", "").replace(" ", "").replace(",", ".")
        try:
            return f"{Decimal(cleaned):.2f}"
        except Exception:  # noqa: BLE001
            return text
    if name == "удалено":
        return "1" if text.lower() in TRUE_VALUES else ""
    if name == "дата":
        return text[:16]
    return text


def row_hash(values: list) -> str:
    """Хеш редактируемой части строки. Считается одинаково при записи и при чтении."""
    payload = "|".join(
        _canonical(name, values[HEADERS.index(name)] if HEADERS.index(name) < len(values) else "")
        for name in EDITABLE
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def to_row(
    tx: Transaction,
    *,
    account_names: dict[str, str],
    category_names: dict[str, str],
    user_names: dict[str, str],
) -> list:
    """Строка для записи. Суммы отдаём числом, чтобы в таблице работали SUM и сводные."""
    amount = float(to_major(tx.amount_minor, tx.currency))
    values = [
        tx.id,
        tx.occurred_at.astimezone(UTC).strftime(DATE_FORMAT),
        _TYPE_TO_RU.get(tx.type, str(tx.type)),
        amount,
        tx.currency,
        account_names.get(tx.account_id, ""),
        account_names.get(tx.counter_account_id or "", ""),
        category_names.get(tx.category_id or "", ""),
        user_names.get(tx.author_id, ""),
        tx.note,
        tx.tags,
        "да" if tx.deleted_at else "",
        str(tx.source),
        tx.updated_at.astimezone(UTC).strftime(DATE_FORMAT),
        "",
    ]
    values[HEADERS.index("sync_hash")] = row_hash(values)
    return values


def parse_row(values: list) -> RowView | None:
    """Разбирает строку таблицы. Возвращает None, если строка пустая."""
    if not values or not any(str(cell).strip() for cell in values):
        return None

    def cell(name: str) -> str:
        index = HEADERS.index(name)
        return str(values[index]).strip() if index < len(values) else ""

    raw_amount = cell("сумма").replace(" ", "").replace(" ", "")
    amount_minor: int | None = None
    if raw_amount:
        try:
            amount_minor = to_minor(Decimal(raw_amount.replace(",", ".")), cell("валюта") or "RUB")
        except Exception:  # noqa: BLE001 — мусор в ячейке не должен ронять синхронизацию
            amount_minor = None

    occurred_at: datetime | None = None
    raw_date = cell("дата")
    if raw_date:
        for pattern in (DATE_FORMAT, "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                occurred_at = datetime.strptime(raw_date, pattern).replace(tzinfo=UTC)
                break
            except ValueError:
                continue

    return RowView(
        id=cell("id"),
        occurred_at=occurred_at,
        tx_type=_RU_TO_TYPE.get(cell("тип").lower()),
        amount_minor=amount_minor,
        category=cell("категория"),
        note=cell("заметка"),
        tags=cell("теги"),
        deleted=cell("удалено").lower() in {"да", "true", "1", "yes", "x"},
        sync_hash=cell("sync_hash"),
    )
