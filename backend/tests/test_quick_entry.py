from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TransactionType
from app.repositories import categories as categories_repo
from app.services import quick_entry


async def test_amount_and_category_by_name(seeded: AsyncSession):
    parsed = await quick_entry.parse(seeded, "500 продукты")
    assert parsed.amount_minor == 50_000
    assert parsed.tx_type == TransactionType.EXPENSE
    assert parsed.category_name == "Продукты"


async def test_amount_with_separators_and_note(seeded: AsyncSession):
    parsed = await quick_entry.parse(seeded, "1 200,50 такси домой")
    assert parsed.amount_minor == 120_050
    # «Такси» — подкатегория «Транспорта», и строка из чата попадает прямо в неё.
    # Название из заметки при этом уходит: дублировать его в категории и в тексте незачем
    assert parsed.category_name == "Такси"
    assert parsed.note == "домой"
    category = await categories_repo.get(seeded, parsed.category_id or "")
    assert category is not None
    parent = await categories_repo.get(seeded, category.parent_id or "")
    assert parent is not None and parent.name == "Транспорт"


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
