from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TransactionType
from app.services import quick_entry


async def test_amount_and_category_by_name(seeded: AsyncSession):
    parsed = await quick_entry.parse(seeded, "500 продукты")
    assert parsed.amount_minor == 50_000
    assert parsed.tx_type == TransactionType.EXPENSE
    assert parsed.category_name == "Продукты"


async def test_amount_with_separators_and_note(seeded: AsyncSession):
    parsed = await quick_entry.parse(seeded, "1 200,50 такси домой")
    assert parsed.amount_minor == 120_050
    assert parsed.category_name == "Транспорт"  # сработало правило «такси»
    assert parsed.note == "такси домой"


async def test_plus_sign_means_income(seeded: AsyncSession):
    parsed = await quick_entry.parse(seeded, "+50000 зарплата")
    assert parsed.tx_type == TransactionType.INCOME
    assert parsed.category_name == "Зарплата"


async def test_bare_amount_has_no_category(seeded: AsyncSession):
    parsed = await quick_entry.parse(seeded, "350")
    assert parsed.amount_minor == 35_000
    assert parsed.category_id is None
    assert parsed.note == ""


async def test_unknown_text_keeps_note(seeded: AsyncSession):
    parsed = await quick_entry.parse(seeded, "99 какая-то ерунда")
    assert parsed.category_id is None
    assert parsed.note == "какая-то ерунда"


async def test_missing_amount_raises(seeded: AsyncSession):
    try:
        await quick_entry.parse(seeded, "просто текст")
    except quick_entry.ParseError:
        return
    raise AssertionError("ожидалась ParseError")
