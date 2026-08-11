from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Transaction, TransactionType, TxSplit
from app.util.dates import now


@dataclass(slots=True)
class TxFilter:
    """Единый набор фильтров для списка и для агрегатов — чтобы цифры в отчёте
    всегда сходились со списком, который видит пользователь."""

    start: datetime | None = None
    end: datetime | None = None
    types: list[TransactionType] = field(default_factory=list)
    category_ids: list[str] = field(default_factory=list)
    account_ids: list[str] = field(default_factory=list)
    author_ids: list[str] = field(default_factory=list)
    search: str | None = None
    include_deleted: bool = False


def _apply(query: Select, flt: TxFilter) -> Select:
    if not flt.include_deleted:
        query = query.where(Transaction.deleted_at.is_(None))
    if flt.start is not None:
        query = query.where(Transaction.occurred_at >= flt.start)
    if flt.end is not None:
        query = query.where(Transaction.occurred_at < flt.end)
    if flt.types:
        query = query.where(Transaction.type.in_(flt.types))
    if flt.category_ids:
        query = query.where(Transaction.category_id.in_(flt.category_ids))
    if flt.account_ids:
        query = query.where(Transaction.account_id.in_(flt.account_ids))
    if flt.author_ids:
        query = query.where(Transaction.author_id.in_(flt.author_ids))
    if flt.search:
        query = query.where(Transaction.note.ilike(f"%{flt.search.strip()}%"))
    return query


async def get(session: AsyncSession, tx_id: str) -> Transaction | None:
    return await session.get(Transaction, tx_id)


async def list_page(
    session: AsyncSession, flt: TxFilter, *, limit: int = 50, offset: int = 0
) -> list[Transaction]:
    query = _apply(select(Transaction), flt)
    query = query.order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
    result = await session.execute(query.limit(limit).offset(offset))
    return list(result.scalars())


async def count(session: AsyncSession, flt: TxFilter) -> int:
    query = _apply(select(func.count(Transaction.id)), flt)
    result = await session.execute(query)
    return int(result.scalar_one())


async def totals_by_type(session: AsyncSession, flt: TxFilter) -> dict[str, int]:
    query = _apply(
        select(Transaction.type, func.sum(Transaction.amount_minor)), flt
    ).group_by(Transaction.type)
    result = await session.execute(query)
    return {str(row[0]): int(row[1] or 0) for row in result}


async def totals_by_category(
    session: AsyncSession, flt: TxFilter
) -> list[tuple[str | None, int, int]]:
    """[(category_id, сумма, количество)] по убыванию суммы."""
    query = _apply(
        select(
            Transaction.category_id,
            func.sum(Transaction.amount_minor),
            func.count(Transaction.id),
        ),
        flt,
    ).group_by(Transaction.category_id)
    result = await session.execute(query)
    rows = [(row[0], int(row[1] or 0), int(row[2])) for row in result]
    return sorted(rows, key=lambda item: item[1], reverse=True)


async def totals_by_author(session: AsyncSession, flt: TxFilter) -> dict[str, int]:
    query = _apply(
        select(Transaction.author_id, func.sum(Transaction.amount_minor)), flt
    ).group_by(Transaction.author_id)
    result = await session.execute(query)
    return {str(row[0]): int(row[1] or 0) for row in result}


async def totals_by_month_category(
    session: AsyncSession, flt: TxFilter
) -> list[tuple[str, str | None, int]]:
    """[(YYYY-MM, category_id, сумма)] — основа помесячного сравнения и LLM-дампа."""
    month = func.strftime("%Y-%m", Transaction.occurred_at)
    query = _apply(
        select(month, Transaction.category_id, func.sum(Transaction.amount_minor)), flt
    ).group_by(month, Transaction.category_id)
    result = await session.execute(query)
    return [(str(row[0]), row[1], int(row[2] or 0)) for row in result]


async def account_deltas(session: AsyncSession) -> dict[str, int]:
    """Изменение остатка каждого счёта по всем неудалённым операциям.

    Считается одним проходом: доход плюсует, расход минусует, перевод уходит с account_id
    и приходит на counter_account_id.
    """
    deltas: dict[str, int] = {}

    query = (
        select(Transaction.account_id, Transaction.type, func.sum(Transaction.amount_minor))
        .where(Transaction.deleted_at.is_(None))
        .group_by(Transaction.account_id, Transaction.type)
    )
    for account_id, tx_type, total in await session.execute(query):
        amount = int(total or 0)
        sign = 1 if tx_type == TransactionType.INCOME else -1
        deltas[account_id] = deltas.get(account_id, 0) + sign * amount

    incoming = (
        select(Transaction.counter_account_id, func.sum(Transaction.amount_minor))
        .where(
            Transaction.deleted_at.is_(None),
            Transaction.type == TransactionType.TRANSFER,
            Transaction.counter_account_id.is_not(None),
        )
        .group_by(Transaction.counter_account_id)
    )
    for account_id, total in await session.execute(incoming):
        deltas[account_id] = deltas.get(account_id, 0) + int(total or 0)

    return deltas


async def paid_by_user(session: AsyncSession, flt: TxFilter) -> dict[str, int]:
    """Сколько каждый фактически заплатил по операциям, у которых есть сплиты."""
    query = _apply(
        select(Transaction.author_id, func.sum(Transaction.amount_minor)).where(
            Transaction.splits.any()
        ),
        flt,
    ).group_by(Transaction.author_id)
    result = await session.execute(query)
    return {str(row[0]): int(row[1] or 0) for row in result}


async def owed_by_user(session: AsyncSession, flt: TxFilter) -> dict[str, int]:
    """Сколько каждому «начислено» по сплитам."""
    query = _apply(
        select(TxSplit.user_id, func.sum(TxSplit.share_minor)).join(
            Transaction, Transaction.id == TxSplit.transaction_id
        ),
        flt,
    ).group_by(TxSplit.user_id)
    result = await session.execute(query)
    return {str(row[0]): int(row[1] or 0) for row in result}


async def soft_delete(session: AsyncSession, tx: Transaction) -> Transaction:
    tx.deleted_at = now()
    await session.flush()
    return tx


async def recent_category_ids(session: AsyncSession, author_id: str, limit: int = 6) -> list[str]:
    """Последние использованные категории — для кнопок быстрого ввода."""
    query = (
        select(Transaction.category_id, func.max(Transaction.occurred_at).label("last_used"))
        .where(
            Transaction.deleted_at.is_(None),
            Transaction.author_id == author_id,
            Transaction.category_id.is_not(None),
            Transaction.type == TransactionType.EXPENSE,
        )
        .group_by(Transaction.category_id)
        .order_by(func.max(Transaction.occurred_at).desc())
        .limit(limit)
    )
    result = await session.execute(query)
    return [str(row[0]) for row in result]
