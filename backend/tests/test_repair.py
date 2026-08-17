"""Разбор взаиморасчётов и починка долей, оставшихся от старой версии.

Баг чинили в коде, но в базе у тех, кто уже успел поправить счёт у операции, остались
доли от траты, которая больше не общая. Исправление кода такие строки не трогает —
оно срабатывает только при следующей правке операции. Здесь проверяется, что команда
их находит и пересчитывает, а настоящий долг оставляет на месте.
"""

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import repair
from app.models import Account, Transaction, TransactionType, User
from app.repositories import accounts as accounts_repo
from app.repositories import users as users_repo
from app.repositories.transactions import TxFilter
from app.security.initdata import TelegramUser, build_init_data
from app.services import bootstrap, ledger
from app.services import stats as stats_service
from tests.conftest import USER_A, USER_B


async def _two_people(session: AsyncSession) -> tuple[User, User, Account]:
    await bootstrap.ensure_reference_data(session)
    people = []
    for payload in (USER_A, USER_B):
        person = await users_repo.upsert_from_telegram(
            session, TelegramUser(id=payload["id"], first_name=payload["first_name"])
        )
        await bootstrap.ensure_personal_account(session, person)
        people.append(person)

    shared = await accounts_repo.create(session, name="Общий счёт", is_shared=True)
    await session.flush()
    return people[0], people[1], shared


async def _personal(session: AsyncSession, user: User) -> Account:
    result = await session.execute(
        select(Account).where(Account.owner_id == user.id, Account.is_shared.is_(False))
    )
    return result.scalars().first()


async def _shared_expense(session: AsyncSession, author: User, shared: Account) -> Transaction:
    return await ledger.create_transaction(
        session,
        author=author,
        tx_type=TransactionType.EXPENSE,
        amount_minor=114_656,
        account_id=shared.id,
        note="продукты",
    )


async def _net(session: AsyncSession) -> list[int]:
    return [item.net_minor for item in await stats_service.settle_up(session, TxFilter())]


async def test_leftover_shares_are_found_and_fixed(session: AsyncSession):
    """Ровно тот случай, о котором сообщили: счёт поправили, а долг остался."""
    anya, _, shared = await _two_people(session)
    tx = await _shared_expense(session, anya, shared)
    mine = await _personal(session, anya)

    # Правка счёта в обход ledger — так операция выглядела после старой версии:
    # счёт уже личный, а доли от общего остались
    await session.execute(
        update(Transaction).where(Transaction.id == tx.id).values(account_id=mine.id)
    )
    await session.flush()
    session.expire_all()

    assert await _net(session) == [57_328, -57_328]

    rows = await repair.scan(session)
    assert [row.problem for row in rows] == [repair.NOT_SHARED]

    assert await repair.repair(session, rows) == 1
    assert await _net(session) == [0, 0]
    assert await repair.scan(session) == []


async def test_real_debt_is_left_alone(session: AsyncSession):
    """Настоящий долг чинить нечего: трата с общего счёта так и остаётся общей."""
    anya, _, shared = await _two_people(session)
    await _shared_expense(session, anya, shared)

    rows = await repair.scan(session)
    assert [row.problem for row in rows] == [None]

    assert await repair.repair(session, rows) == 0
    assert await _net(session) == [57_328, -57_328]


async def test_shares_on_income_are_flagged(session: AsyncSession):
    """Доход не делится — доли на нём взяться могли только от старой правки типа."""
    anya, boris, shared = await _two_people(session)
    tx = await _shared_expense(session, anya, shared)
    await session.execute(
        update(Transaction).where(Transaction.id == tx.id).values(type=TransactionType.INCOME)
    )
    await session.flush()
    session.expire_all()

    rows = await repair.scan(session)
    assert [row.problem for row in rows] == [repair.NOT_EXPENSE]
    assert await repair.repair(session, rows) == 1
    assert await _net(session) == [0, 0]


async def test_unbalanced_shares_are_flagged(session: AsyncSession):
    """Сумма долей обязана равняться сумме операции — иначе долг ниоткуда."""
    anya, _, shared = await _two_people(session)
    tx = await _shared_expense(session, anya, shared)
    await session.execute(
        update(Transaction).where(Transaction.id == tx.id).values(amount_minor=200_000)
    )
    await session.flush()
    session.expire_all()

    rows = await repair.scan(session)
    assert [row.problem for row in rows] == [repair.UNBALANCED]

    await repair.repair(session, rows)
    fixed = await repair.scan(session)
    assert [row.problem for row in fixed] == [None]
    assert sum(fixed[0].shares.values()) == 200_000


async def test_editing_the_account_today_needs_no_repair(auth_client: httpx.AsyncClient):
    """Нынешняя правка чинит себя сама — команда нужна только для старых данных."""
    await auth_client.post(
        "/api/auth/login", json={"init_data": build_init_data("123456:TEST-TOKEN", USER_B)}
    )
    shared = (
        await auth_client.post("/api/accounts", json={"name": "Общий", "is_shared": True})
    ).json()
    me = (await auth_client.get("/api/me")).json()
    mine = next(
        account
        for account in (await auth_client.get("/api/accounts")).json()
        if account["owner_id"] == me["id"] and not account["is_shared"]
    )
    created = (
        await auth_client.post(
            "/api/transactions",
            json={"type": "expense", "amount": "1146,56", "account_id": shared["id"]},
        )
    ).json()

    await auth_client.patch(
        f"/api/transactions/{created['id']}", json={"account_id": mine["id"]}
    )

    settle = (await auth_client.get("/api/stats/settle")).json()
    assert [row["net_minor"] for row in settle["users"]] == [0, 0]
