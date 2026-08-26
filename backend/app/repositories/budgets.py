"""Месячные лимиты по категориям."""

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Budget


async def list_all(session: AsyncSession) -> list[Budget]:
    result = await session.execute(select(Budget))
    return list(result.scalars())


async def by_category(session: AsyncSession) -> dict[str, int]:
    """{category_id: лимит} — в таком виде лимиты нужны отчёту."""
    return {budget.category_id: budget.limit_minor for budget in await list_all(session)}


async def get(session: AsyncSession, category_id: str) -> Budget | None:
    result = await session.execute(select(Budget).where(Budget.category_id == category_id))
    return result.scalar_one_or_none()


async def upsert(session: AsyncSession, *, category_id: str, limit_minor: int) -> Budget:
    """Задать или изменить лимит. Ноль — тоже лимит: «на такси не тратим вовсе»."""
    budget = await get(session, category_id)
    if budget is None:
        budget = Budget(category_id=category_id, limit_minor=limit_minor)
        session.add(budget)
    else:
        budget.limit_minor = limit_minor
    await session.flush()
    return budget


async def remove(session: AsyncSession, category_id: str) -> int:
    result = await session.execute(sql_delete(Budget).where(Budget.category_id == category_id))
    await session.flush()
    return int(result.rowcount or 0)
