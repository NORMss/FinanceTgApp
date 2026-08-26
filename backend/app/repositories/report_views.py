"""Сохранённые виды отчёта — личные наборы фильтров."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReportView


async def list_for(session: AsyncSession, owner_id: str) -> list[ReportView]:
    query = (
        select(ReportView)
        .where(ReportView.owner_id == owner_id)
        .order_by(ReportView.sort, ReportView.name)
    )
    result = await session.execute(query)
    return list(result.scalars())


async def get(session: AsyncSession, view_id: str) -> ReportView | None:
    return await session.get(ReportView, view_id)


async def get_by_name(session: AsyncSession, owner_id: str, name: str) -> ReportView | None:
    query = select(ReportView).where(
        ReportView.owner_id == owner_id, ReportView.name.ilike(name.strip())
    )
    result = await session.execute(query.limit(1))
    return result.scalar_one_or_none()


async def save(
    session: AsyncSession, *, owner_id: str, name: str, payload: str, sort: int = 100
) -> ReportView:
    """Создаёт вид или перезаписывает одноимённый.

    Перезапись, а не ошибка: «сохранить как „Быт“» второй раз означает «я поправил
    фильтры и хочу, чтобы под этим именем лежали новые» — заставлять человека
    сначала удалять старый было бы лишним шагом ради формальности.
    """
    view = await get_by_name(session, owner_id, name)
    if view is None:
        view = ReportView(owner_id=owner_id, name=name.strip(), payload=payload, sort=sort)
        session.add(view)
    else:
        view.payload = payload
        view.sort = sort
    await session.flush()
    return view


async def remove(session: AsyncSession, view: ReportView) -> None:
    await session.delete(view)
    await session.flush()
