from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, AccountKind


async def get(session: AsyncSession, account_id: str) -> Account | None:
    return await session.get(Account, account_id)


async def list_all(session: AsyncSession, *, include_archived: bool = False) -> list[Account]:
    query = select(Account).order_by(Account.sort, Account.name)
    if not include_archived:
        query = query.where(Account.archived.is_(False))
    result = await session.execute(query)
    return list(result.scalars())


async def get_shared(session: AsyncSession) -> Account | None:
    result = await session.execute(
        select(Account)
        .where(Account.is_shared.is_(True), Account.archived.is_(False))
        .order_by(Account.sort)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_personal(session: AsyncSession, owner_id: str) -> Account | None:
    result = await session.execute(
        select(Account)
        .where(
            Account.owner_id == owner_id,
            Account.is_shared.is_(False),
            Account.archived.is_(False),
        )
        .order_by(Account.sort)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def default_for(session: AsyncSession, owner_id: str) -> Account | None:
    """Счёт, на который пишется операция, если счёт не выбран явно.

    Свой личный, и только если его почему-то нет — общий. Раньше умолчанием был общий
    счёт, и это оказалось неверно: большая часть трат в семье всё-таки личная, а каждая
    попавшая на общий счёт трата создаёт долг второму участнику, которого не было.
    Общий счёт остаётся, но теперь его выбирают осознанно.
    """
    return await get_personal(session, owner_id) or await get_shared(session)


async def create(
    session: AsyncSession,
    *,
    name: str,
    kind: AccountKind = AccountKind.CARD,
    currency: str = "RUB",
    is_shared: bool = False,
    owner_id: str | None = None,
    opening_balance_minor: int = 0,
    sort: int = 100,
) -> Account:
    account = Account(
        name=name,
        kind=kind,
        currency=currency,
        is_shared=is_shared,
        owner_id=owner_id,
        opening_balance_minor=opening_balance_minor,
        sort=sort,
    )
    session.add(account)
    await session.flush()
    return account
