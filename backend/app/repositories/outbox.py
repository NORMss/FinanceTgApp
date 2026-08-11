from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OutboxOp, SyncOutbox
from app.util.dates import now


async def enqueue(
    session: AsyncSession, *, entity: str, entity_id: str, op: OutboxOp = OutboxOp.UPSERT
) -> None:
    session.add(SyncOutbox(entity=entity, entity_id=entity_id, op=op))


async def take_pending(session: AsyncSession, limit: int = 200) -> list[SyncOutbox]:
    result = await session.execute(
        select(SyncOutbox)
        .where(SyncOutbox.processed_at.is_(None))
        .order_by(SyncOutbox.id)
        .limit(limit)
    )
    return list(result.scalars())


async def pending_count(session: AsyncSession) -> int:
    result = await session.execute(
        select(SyncOutbox.id).where(SyncOutbox.processed_at.is_(None)).limit(1000)
    )
    return len(list(result.scalars()))


async def mark_done(session: AsyncSession, items: list[SyncOutbox]) -> None:
    stamp = now()
    for item in items:
        item.processed_at = stamp
        item.last_error = None


async def mark_failed(session: AsyncSession, items: list[SyncOutbox], error: str) -> None:
    for item in items:
        item.attempts += 1
        item.last_error = error[:500]


async def purge_processed(session: AsyncSession, keep_last: int = 1000) -> int:
    """Обработанные записи не нужны, но последние оставляем для разбора инцидентов."""
    result = await session.execute(
        select(SyncOutbox.id)
        .where(SyncOutbox.processed_at.is_not(None))
        .order_by(SyncOutbox.id.desc())
        .offset(keep_last)
    )
    stale_ids = [row for row in result.scalars()]
    if not stale_ids:
        return 0
    for chunk_start in range(0, len(stale_ids), 500):
        chunk = stale_ids[chunk_start : chunk_start + 500]
        await session.execute(
            SyncOutbox.__table__.delete().where(SyncOutbox.id.in_(chunk))
        )
    return len(stale_ids)
