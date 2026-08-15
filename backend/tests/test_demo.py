"""Генератор демо-данных.

Демо — это витрина проекта: если оно сломается, первое впечатление о приложении
будет складываться из трейсбека. Проверяем не красоту цифр, а то, что журнал
действительно наполнен и связан правильно.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import demo
from app.models import Category, Transaction, TransactionType, TxSplit, User
from app.util.dates import resolve_period


async def _count(session: AsyncSession, model) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar_one())


async def test_seed_fills_journal(session: AsyncSession):
    result = await demo.seed(session, months=2)

    assert result["people"] == ["Аня", "Борис"]
    assert result["transactions"] > 100
    assert await _count(session, User) == 2
    assert await _count(session, Transaction) == result["transactions"]


async def test_seed_uses_subcategories(session: AsyncSession):
    """Ради подкатегорий всё и затевалось — в демо они должны быть видны."""
    await demo.seed(session, months=2)

    rows = await session.execute(
        select(Category.name)
        .join(Transaction, Transaction.category_id == Category.id)
        .where(Category.parent_id.is_not(None))
        .distinct()
    )
    used = set(rows.scalars())
    assert {"Пятёрочка", "Такси"} <= used


async def test_shared_expenses_are_split_between_two(session: AsyncSession):
    """С двумя участниками траты с общего счёта делятся — на этом ловился баг со схемой."""
    await demo.seed(session, months=2)

    assert await _count(session, TxSplit) > 0
    rows = await session.execute(
        select(func.count()).select_from(TxSplit).group_by(TxSplit.transaction_id).limit(5)
    )
    assert all(count == 2 for count in rows.scalars())


async def test_seed_covers_current_month(session: AsyncSession):
    """Период «Месяц» открыт по умолчанию: если в нём пусто, демо показывает нули."""
    await demo.seed(session, months=2)

    start, end = resolve_period("month")
    count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Transaction)
                .where(Transaction.occurred_at >= start, Transaction.occurred_at < end)
            )
        ).scalar_one()
    )
    assert count > 10


async def test_income_and_transfers_present(session: AsyncSession):
    """Зарплаты и переводы нужны, чтобы работали остатки и взаиморасчёты."""
    await demo.seed(session, months=2)

    rows = await session.execute(
        select(Transaction.type, func.count()).group_by(Transaction.type)
    )
    kinds = {str(row[0]): row[1] for row in rows}
    assert kinds.get(TransactionType.INCOME.value, 0) > 0
    assert kinds.get(TransactionType.TRANSFER.value, 0) > 0


async def test_refuses_to_overwrite_existing_journal(session: AsyncSession):
    """Защита от запуска на рабочей базе: без --reset демо ничего не стирает."""
    await demo.seed(session, months=1)
    before = await _count(session, Transaction)

    with pytest.raises(demo.DemoError):
        await demo.seed(session, months=1)

    assert await _count(session, Transaction) == before

    await demo.seed(session, months=1, reset=True)
    assert await _count(session, Transaction) == before
