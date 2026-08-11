"""Проверки соответствия «операция <-> строка таблицы».

Самое хрупкое место синхронизации — стабильность хеша: если он «плывёт» от форматирования,
приложение решит, что человек правил каждую строку, и начнёт затирать данные.
"""

from datetime import UTC, datetime

from app.models import Transaction, TransactionType, TxSource
from app.sync.mapping import HEADERS, parse_row, row_hash, to_row


def _tx() -> Transaction:
    return Transaction(
        id="01J0000000000000000000000A",
        occurred_at=datetime(2026, 8, 11, 14, 30, tzinfo=UTC),
        type=TransactionType.EXPENSE,
        amount_minor=123_456,
        currency="RUB",
        account_id="acc",
        category_id="cat",
        author_id="usr",
        note="продукты",
        tags="",
        source=TxSource.APP,
        created_at=datetime(2026, 8, 11, 14, 30, tzinfo=UTC),
        updated_at=datetime(2026, 8, 11, 14, 30, tzinfo=UTC),
    )


def _row() -> list:
    return to_row(
        _tx(),
        account_names={"acc": "Общий счёт"},
        category_names={"cat": "Продукты"},
        user_names={"usr": "Аня"},
    )


def test_row_matches_headers():
    assert len(_row()) == len(HEADERS)


def test_row_round_trip():
    view = parse_row(_row())
    assert view is not None
    assert view.id == "01J0000000000000000000000A"
    assert view.amount_minor == 123_456
    assert view.tx_type == TransactionType.EXPENSE
    assert view.category == "Продукты"
    assert view.occurred_at == datetime(2026, 8, 11, 14, 30, tzinfo=UTC)
    assert view.deleted is False


def test_hash_survives_google_formatting():
    """Google возвращает число как 1234.56 или «1 234,56» — хеш обязан совпасть."""
    row = _row()
    stored = row[HEADERS.index("sync_hash")]

    as_text = list(row)
    as_text[HEADERS.index("сумма")] = "1 234,56"
    assert row_hash(as_text) == stored

    as_int_like = list(row)
    as_int_like[HEADERS.index("сумма")] = 1234.56
    assert row_hash(as_int_like) == stored


def test_hash_changes_when_human_edits():
    row = _row()
    stored = row[HEADERS.index("sync_hash")]
    row[HEADERS.index("заметка")] = "поправил руками"
    assert row_hash(row) != stored


def test_empty_row_is_ignored():
    assert parse_row([]) is None
    assert parse_row(["", "", ""]) is None
