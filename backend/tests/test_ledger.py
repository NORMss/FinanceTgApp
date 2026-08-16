import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TransactionType
from app.repositories import accounts as accounts_repo
from app.repositories import outbox as outbox_repo
from app.repositories import users as users_repo
from app.repositories.transactions import TxFilter
from app.security.initdata import TelegramUser
from app.services import bootstrap, ledger
from app.services import stats as stats_service


async def _two_users(session: AsyncSession):
    """Двое участников, у каждого личный счёт, плюс общий кошелёк.

    Общий счёт приложение само не заводит — им пользуются осознанно, — поэтому
    здесь он создаётся явно: почти все проверки ниже как раз про деление трат.
    """
    await bootstrap.ensure_reference_data(session)
    first = await users_repo.upsert_from_telegram(session, TelegramUser(id=111, first_name="Аня"))
    second = await users_repo.upsert_from_telegram(session, TelegramUser(id=222, first_name="Боря"))
    await bootstrap.ensure_personal_account(session, first)
    await bootstrap.ensure_personal_account(session, second)
    await bootstrap.ensure_shared_account(session)
    await session.flush()
    return first, second


async def test_shared_expense_is_split_evenly(session: AsyncSession):
    anya, borya = await _two_users(session)
    shared = await accounts_repo.get_shared(session)

    tx = await ledger.create_transaction(
        session,
        author=anya,
        tx_type=TransactionType.EXPENSE,
        amount_minor=100_01,
        account_id=shared.id,
        note="продукты",
    )

    assert sum(split.share_minor for split in tx.splits) == 100_01
    assert {split.user_id for split in tx.splits} == {anya.id, borya.id}


async def test_personal_expense_is_not_split(session: AsyncSession):
    anya, _ = await _two_users(session)
    personal = await bootstrap.ensure_personal_account(session, anya)

    tx = await ledger.create_transaction(
        session,
        author=anya,
        tx_type=TransactionType.EXPENSE,
        amount_minor=5000,
        account_id=personal.id,
    )
    assert tx.splits == []


async def test_explicit_splits_must_match_amount(session: AsyncSession):
    anya, borya = await _two_users(session)
    shared = await accounts_repo.get_shared(session)

    with pytest.raises(ledger.LedgerError):
        await ledger.create_transaction(
            session,
            author=anya,
            tx_type=TransactionType.EXPENSE,
            amount_minor=1000,
            account_id=shared.id,
            splits={anya.id: 400, borya.id: 400},
        )


async def test_transfer_requires_other_account(session: AsyncSession):
    anya, _ = await _two_users(session)
    shared = await accounts_repo.get_shared(session)

    with pytest.raises(ledger.LedgerError):
        await ledger.create_transaction(
            session,
            author=anya,
            tx_type=TransactionType.TRANSFER,
            amount_minor=1000,
            account_id=shared.id,
            counter_account_id=shared.id,
        )


async def test_balances_follow_transactions(session: AsyncSession):
    anya, _ = await _two_users(session)
    shared = await accounts_repo.get_shared(session)
    personal = await bootstrap.ensure_personal_account(session, anya)

    await ledger.create_transaction(
        session,
        author=anya,
        tx_type=TransactionType.INCOME,
        amount_minor=100_000,
        account_id=shared.id,
    )
    await ledger.create_transaction(
        session,
        author=anya,
        tx_type=TransactionType.EXPENSE,
        amount_minor=30_000,
        account_id=shared.id,
    )
    await ledger.create_transaction(
        session,
        author=anya,
        tx_type=TransactionType.TRANSFER,
        amount_minor=20_000,
        account_id=shared.id,
        counter_account_id=personal.id,
    )

    balances, _total = await stats_service.account_balances(session)
    by_id = {item.account_id: item.balance_minor for item in balances}
    assert by_id[shared.id] == 50_000
    assert by_id[personal.id] == 20_000


async def test_settle_up_shows_who_owes(session: AsyncSession):
    anya, borya = await _two_users(session)
    shared = await accounts_repo.get_shared(session)

    # Аня заплатила 1000 с общего счёта, делится пополам -> Боря должен ей 500
    await ledger.create_transaction(
        session,
        author=anya,
        tx_type=TransactionType.EXPENSE,
        amount_minor=1000,
        account_id=shared.id,
    )

    balances = {item.user_id: item.net_minor for item in await stats_service.settle_up(session)}
    assert balances[anya.id] == 500
    assert balances[borya.id] == -500


async def test_deleted_transaction_leaves_balance_untouched(session: AsyncSession):
    anya, _ = await _two_users(session)
    shared = await accounts_repo.get_shared(session)

    tx = await ledger.create_transaction(
        session,
        author=anya,
        tx_type=TransactionType.EXPENSE,
        amount_minor=7000,
        account_id=shared.id,
    )
    await ledger.delete_transaction(session, tx)

    balances, _ = await stats_service.account_balances(session)
    assert {item.account_id: item.balance_minor for item in balances}[shared.id] == 0


async def test_every_change_lands_in_outbox(session: AsyncSession):
    anya, _ = await _two_users(session)
    shared = await accounts_repo.get_shared(session)

    tx = await ledger.create_transaction(
        session,
        author=anya,
        tx_type=TransactionType.EXPENSE,
        amount_minor=1500,
        account_id=shared.id,
    )
    await ledger.update_transaction(session, tx, note="уточнил")
    await session.flush()

    pending = await outbox_repo.take_pending(session)
    assert [item.entity_id for item in pending] == [tx.id, tx.id]


async def test_summary_counts_only_period(session: AsyncSession):
    from datetime import UTC, datetime

    anya, _ = await _two_users(session)
    shared = await accounts_repo.get_shared(session)

    await ledger.create_transaction(
        session,
        author=anya,
        tx_type=TransactionType.EXPENSE,
        amount_minor=1000,
        account_id=shared.id,
        occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
    )
    await ledger.create_transaction(
        session,
        author=anya,
        tx_type=TransactionType.EXPENSE,
        amount_minor=2000,
        account_id=shared.id,
        occurred_at=datetime(2026, 2, 15, tzinfo=UTC),
    )

    summary = await stats_service.period_summary(
        session,
        TxFilter(start=datetime(2026, 2, 1, tzinfo=UTC), end=datetime(2026, 3, 1, tzinfo=UTC)),
    )
    assert summary["expense_minor"] == 2000
