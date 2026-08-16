"""Создание и изменение операций — единственная точка записи в журнал.

Любая мутация транзакции обязана пройти через этот модуль: он проверяет инварианты,
считает сплиты и кладёт запись в outbox для выгрузки в Google Sheets. Если писать
в БД мимо него, таблица разъедется с приложением.
"""

from datetime import datetime
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Transaction, TransactionType, TxSource, TxSplit, User
from app.repositories import accounts as accounts_repo
from app.repositories import outbox as outbox_repo
from app.repositories import users as users_repo
from app.util.dates import now
from app.util.money import split_evenly

ENTITY = "transaction"


class UnsetType:
    """Отличает «поле не передали» от «передали null».

    Без этого нельзя снять категорию с операции: `category_id=None` читается и как
    «не трогай», и как «очисти», а нужно и то, и другое.
    """

    def __repr__(self) -> str:  # pragma: no cover — только для отладочного вывода
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET: Final = UnsetType()


class LedgerError(ValueError):
    """Нарушен инвариант журнала. Наружу отдаётся как 400."""


async def _resolve_splits(
    session: AsyncSession,
    *,
    account: Account,
    tx_type: TransactionType,
    amount_minor: int,
    explicit: dict[str, int] | None,
) -> dict[str, int]:
    """Правило по умолчанию: трата с общего счёта делится поровну между активными
    пользователями, всё остальное не делится. Явно переданные доли всегда важнее.
    """
    if explicit is not None:
        total = sum(explicit.values())
        if explicit and total != amount_minor:
            raise LedgerError(
                f"сумма долей ({total}) не равна сумме операции ({amount_minor})"
            )
        return explicit

    if tx_type != TransactionType.EXPENSE or not account.is_shared:
        return {}

    participants = [user for user in await users_repo.list_all(session) if user.is_active]
    if len(participants) < 2:
        return {}
    shares = split_evenly(amount_minor, len(participants))
    return {user.id: share for user, share in zip(participants, shares, strict=True)}


async def create_transaction(
    session: AsyncSession,
    *,
    author: User,
    tx_type: TransactionType,
    amount_minor: int,
    account_id: str,
    occurred_at: datetime | None = None,
    counter_account_id: str | None = None,
    category_id: str | None = None,
    currency: str | None = None,
    note: str = "",
    tags: str = "",
    source: TxSource = TxSource.APP,
    external_id: str | None = None,
    splits: dict[str, int] | None = None,
) -> Transaction:
    if amount_minor <= 0:
        raise LedgerError("сумма должна быть положительной")

    account = await accounts_repo.get(session, account_id)
    if account is None:
        raise LedgerError("счёт не найден")

    if tx_type == TransactionType.TRANSFER:
        if not counter_account_id:
            raise LedgerError("для перевода нужен счёт назначения")
        if counter_account_id == account_id:
            raise LedgerError("нельзя перевести на тот же счёт")
        if await accounts_repo.get(session, counter_account_id) is None:
            raise LedgerError("счёт назначения не найден")
        category_id = None
    else:
        counter_account_id = None

    tx = Transaction(
        occurred_at=occurred_at or now(),
        type=tx_type,
        amount_minor=amount_minor,
        currency=(currency or account.currency).upper(),
        account_id=account_id,
        counter_account_id=counter_account_id,
        category_id=category_id,
        author_id=author.id,
        note=note.strip(),
        tags=tags.strip(),
        source=source,
        external_id=external_id,
    )

    resolved = await _resolve_splits(
        session,
        account=account,
        tx_type=tx_type,
        amount_minor=amount_minor,
        explicit=splits,
    )
    tx.splits = [
        TxSplit(user_id=user_id, share_minor=share) for user_id, share in resolved.items() if share
    ]

    session.add(tx)
    await session.flush()
    await outbox_repo.enqueue(session, entity=ENTITY, entity_id=tx.id)
    return tx


async def update_transaction(
    session: AsyncSession,
    tx: Transaction,
    *,
    amount_minor: int | None = None,
    occurred_at: datetime | None = None,
    tx_type: TransactionType | None = None,
    category_id: str | None | UnsetType = UNSET,
    account_id: str | None = None,
    counter_account_id: str | None | UnsetType = UNSET,
    note: str | None = None,
    tags: str | None = None,
    splits: dict[str, int] | None | UnsetType = UNSET,
) -> Transaction:
    """Правит существующую операцию. Не переданные поля остаются как были.

    Менять можно всё, включая тип: «записал как расход, а это был доход» — самая
    частая ошибка ввода, и переписывать операцию заново ради этого не нужно.
    """
    if amount_minor is not None:
        if amount_minor <= 0:
            raise LedgerError("сумма должна быть положительной")
        tx.amount_minor = amount_minor
    if occurred_at is not None:
        tx.occurred_at = occurred_at
    if tx_type is not None:
        tx.type = tx_type
    if account_id is not None:
        if await accounts_repo.get(session, account_id) is None:
            raise LedgerError("счёт не найден")
        tx.account_id = account_id
    if not isinstance(category_id, UnsetType):
        tx.category_id = category_id or None
    if not isinstance(counter_account_id, UnsetType):
        tx.counter_account_id = counter_account_id or None
    if note is not None:
        tx.note = note.strip()
    if tags is not None:
        tx.tags = tags.strip()

    if tx.type == TransactionType.TRANSFER:
        if not tx.counter_account_id:
            raise LedgerError("для перевода нужен счёт назначения")
        if tx.counter_account_id == tx.account_id:
            raise LedgerError("нельзя перевести на тот же счёт")
        if await accounts_repo.get(session, tx.counter_account_id) is None:
            raise LedgerError("счёт назначения не найден")
        # У перевода нет категории: деньги не потрачены, а переложены
        tx.category_id = None
    else:
        tx.counter_account_id = None

    account = await accounts_repo.get(session, tx.account_id)
    assert account is not None  # проверено выше либо при создании

    # Доли пересчитываем, когда изменилось хоть что-то, от чего они зависят.
    # Счёт в этом списке обязателен: перенос траты с общего счёта на личный означает,
    # что делить больше нечего, — а без пересчёта старые доли остаются в базе, и раздел
    # «кто кому должен» продолжает показывать долг по операции, которая уже личная
    if (
        not isinstance(splits, UnsetType)
        or amount_minor is not None
        or tx_type is not None
        or account_id is not None
    ):
        resolved = await _resolve_splits(
            session,
            account=account,
            tx_type=tx.type,
            amount_minor=tx.amount_minor,
            explicit=None if isinstance(splits, UnsetType) else splits,
        )
        tx.splits = [
            TxSplit(user_id=user_id, share_minor=share)
            for user_id, share in resolved.items()
            if share
        ]

    await session.flush()
    await outbox_repo.enqueue(session, entity=ENTITY, entity_id=tx.id)
    return tx


async def delete_transaction(session: AsyncSession, tx: Transaction) -> Transaction:
    """Мягкое удаление: строка остаётся и в БД, и в таблице, но помечается удалённой."""
    tx.deleted_at = now()
    await session.flush()
    await outbox_repo.enqueue(session, entity=ENTITY, entity_id=tx.id)
    return tx
