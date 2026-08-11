import pytest

from app.util.ids import is_ulid, new_ulid
from app.util.money import format_amount, split_evenly, to_major, to_minor


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("500", 50000),
        ("500.5", 50050),
        ("500,55", 50055),
        ("1 234,56", 123456),
        ("0.01", 1),
        (1000, 100000),
    ],
)
def test_to_minor(raw, expected):
    assert to_minor(raw, "RUB") == expected


def test_to_minor_rejects_garbage():
    with pytest.raises(ValueError):
        to_minor("абв", "RUB")
    with pytest.raises(ValueError):
        to_minor("", "RUB")


def test_zero_decimal_currency():
    assert to_minor("500", "JPY") == 500
    assert to_major(500, "JPY") == 500


def test_rounding_is_half_up():
    assert to_minor("0.005", "RUB") == 1
    assert to_minor("0.004", "RUB") == 0


def test_format_amount():
    assert format_amount(123456) == "1 234.56"  # разряды разделены неразрывным пробелом
    assert format_amount(-5000) == "-50.00"
    assert format_amount(5000, sign=True) == "+50.00"


def test_split_evenly_keeps_every_kopek():
    shares = split_evenly(1001, 3)
    assert sum(shares) == 1001
    assert shares == [334, 334, 333]


def test_ulid_is_sortable_and_valid():
    first = new_ulid(1_000_000)
    second = new_ulid(2_000_000)
    assert first < second
    assert is_ulid(first) and len(first) == 26
