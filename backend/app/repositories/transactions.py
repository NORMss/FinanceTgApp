from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import ColumnElement, Select, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Transaction, TransactionType, TxSplit
from app.util.dates import now


@dataclass(slots=True)
class TxFilter:
    """Единый набор фильтров для списка и для агрегатов — чтобы цифры в отчёте
    всегда сходились со списком, который видит пользователь.

    Включающие и исключающие поля идут парами (`category_ids` / `exclude_category_ids`)
    и применяются вместе: сначала оставляем выбранное, потом вычитаем скрытое. Порядок
    не важен — оба условия попадают в один WHERE.
    """

    start: datetime | None = None
    end: datetime | None = None
    types: list[TransactionType] = field(default_factory=list)
    category_ids: list[str] = field(default_factory=list)
    account_ids: list[str] = field(default_factory=list)
    # «Кто записал» — про действие ввода, а не про деньги. Нужен там, где важен сам
    # факт записи: вечернее напоминание идёт тому, кто за день ничего не внёс
    author_ids: list[str] = field(default_factory=list)
    # «Чья трата» — про деньги. Именно это спрашивают история и отчёт
    person_ids: list[str] = field(default_factory=list)
    search: str | None = None
    include_deleted: bool = False

    # --- исключения: «сколько мы тратим, если не считать ипотеку и отпуск» ---
    exclude_category_ids: list[str] = field(default_factory=list)
    # Операции без категории исключаются отдельно: NULL нельзя перечислить в списке id
    exclude_uncategorized: bool = False
    tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)


def _tag_match(tag: str):
    """Условие «у операции есть эта метка».

    Метки лежат плоской строкой через запятую, поэтому голый LIKE '%отпуск%' поймал бы
    и «отпускные». Обкладываем и колонку, и образец запятыми — тогда совпадение
    возможно только по целой метке.
    """
    haystack = literal(",") + func.lower(Transaction.tags) + literal(",")
    return haystack.like(f"%,{tag},%")


def person_id() -> ColumnElement[str]:
    """Чья это операция: владелец счёта, а если владельца нет — тот, кто её записал.

    Записать за другого — значит выбрать его личный счёт: «Аня купила Боре лекарства»
    в журнале выглядит как трата со счёта «Личный · Боря», автор при этом Аня. Считать
    такую операцию Аниной неверно: деньги ушли за Борю, и в его истории она должна быть.

    Владельца нет у общего счёта — там трата и правда общая, и относится она к тому,
    кто её записал: ровно так же её считают «Взаиморасчёты».
    """
    owner = (
        select(Account.owner_id)
        .where(Account.id == Transaction.account_id)
        .correlate(Transaction)
        .scalar_subquery()
    )
    return func.coalesce(owner, Transaction.author_id)


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
    if flt.person_ids:
        query = query.where(person_id().in_(flt.person_ids))
    if flt.search:
        query = query.where(Transaction.note.ilike(f"%{flt.search.strip()}%"))

    if flt.exclude_category_ids:
        # NOT IN роняет строки с NULL: «NULL NOT IN (...)» в SQL — это NULL, а не
        # истина. Без первой половины условия исключение одной категории молча
        # выкинуло бы из отчёта все операции, у которых категории нет вовсе,
        # и итог перестал бы сходиться со списком в Истории.
        query = query.where(
            or_(
                Transaction.category_id.is_(None),
                Transaction.category_id.notin_(flt.exclude_category_ids),
            )
        )
    if flt.exclude_uncategorized:
        query = query.where(Transaction.category_id.is_not(None))
    if flt.tags:
        query = query.where(or_(*(_tag_match(tag) for tag in flt.tags)))
    for tag in flt.exclude_tags:
        query = query.where(~_tag_match(tag))
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


async def totals_by_person(session: AsyncSession, flt: TxFilter) -> dict[str, int]:
    """Сколько потрачено за каждого. Разбивка та же, что и у фильтра списка."""
    person = person_id()
    query = _apply(select(person, func.sum(Transaction.amount_minor)), flt).group_by(person)
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


async def totals_by_month_type(session: AsyncSession, flt: TxFilter) -> list[tuple[str, str, int]]:
    """[(YYYY-MM, тип, сумма)] — столбики доходов и расходов на графике динамики."""
    month = func.strftime("%Y-%m", Transaction.occurred_at)
    query = _apply(
        select(month, Transaction.type, func.sum(Transaction.amount_minor)), flt
    ).group_by(month, Transaction.type)
    result = await session.execute(query)
    return [(str(row[0]), str(row[1]), int(row[2] or 0)) for row in result]


async def largest(session: AsyncSession, flt: TxFilter, *, limit: int = 5) -> list[Transaction]:
    """Самые крупные операции периода — по убыванию суммы.

    Отдельный запрос, а не сортировка уже загруженной страницы: страница
    отсортирована по дате, и крупная трата из начала месяца в неё не попадёт.
    """
    query = _apply(select(Transaction), flt).order_by(
        Transaction.amount_minor.desc(), Transaction.occurred_at.desc()
    )
    result = await session.execute(query.limit(limit))
    return list(result.scalars())


async def spend_by_user(session: AsyncSession, flt: TxFilter) -> dict[str, int]:
    """Чья это трата по долям — в отличие от `totals_by_person`, который смотрит на счёт.

    Расхождение ровно одно, и оно на общем счёте. У общего счёта нет владельца,
    поэтому `person_id()` относит трату к тому, кто её записал, — трата на 4 000
    целиком числится за одним. Но делится она пополам, и второму начислено 2 000.

    Обе цифры верны и отвечают на разные вопросы: «с чьего счёта ушло» и «на кого
    записано». Отчёт показывает первую, а переключателем «по долям» — вторую.
    Там, где доли есть, берём их; где нет (личная трата) — всю сумму автору.
    Складывать эти два источника корректно: операция либо поделена, либо нет.
    """
    totals: dict[str, int] = {}

    shared = _apply(
        select(TxSplit.user_id, func.sum(TxSplit.share_minor)).join(
            Transaction, Transaction.id == TxSplit.transaction_id
        ),
        flt,
    ).group_by(TxSplit.user_id)
    for user_id, amount in await session.execute(shared):
        totals[str(user_id)] = totals.get(str(user_id), 0) + int(amount or 0)

    personal = _apply(
        select(Transaction.author_id, func.sum(Transaction.amount_minor)).where(
            ~Transaction.splits.any()
        ),
        flt,
    ).group_by(Transaction.author_id)
    for user_id, amount in await session.execute(personal):
        totals[str(user_id)] = totals.get(str(user_id), 0) + int(amount or 0)

    return totals


async def repeated_notes(
    session: AsyncSession, flt: TxFilter, *, limit: int = 8
) -> list[tuple[str, int, int]]:
    """[(комментарий, сколько раз, сумма)] для трат, повторившихся за период.

    Дешёвая замена настоящему распознаванию подписок: «яндекс плюс» четыре месяца
    подряд одной и той же строкой — это и есть подписка, и увидеть её в отчёте
    полезнее, чем не увидеть, ожидая идеального алгоритма.

    Группируем в Python, а не в SQL: встроенный `lower()` в SQLite работает только
    с латиницей, и «Яндекс Плюс» с «яндекс плюс» разъехались бы на две подписки.
    Читаем две колонки за период — это дешевле, чем кажется, и одинаково ведёт себя
    на любой базе.
    """
    query = _apply(select(Transaction.note, Transaction.amount_minor), flt).where(
        func.trim(Transaction.note) != ""
    )
    groups: dict[str, list[int]] = {}
    for note, amount in await session.execute(query):
        groups.setdefault(" ".join(str(note).split()).lower(), []).append(int(amount or 0))

    repeated = (
        (note, len(amounts), sum(amounts)) for note, amounts in groups.items() if len(amounts) > 1
    )
    return sorted(repeated, key=lambda item: item[2], reverse=True)[:limit]


async def known_tags(session: AsyncSession) -> list[tuple[str, int]]:
    """Все встречавшиеся метки и как часто. Разбор в Python — меток единицы.

    В SQLite нет разворачивания строки в строки таблицы, а держать ради этого
    отдельную таблицу меток на две сотни операций в месяц незачем.
    """
    query = select(Transaction.tags).where(
        Transaction.deleted_at.is_(None), func.trim(Transaction.tags) != ""
    )
    counts: dict[str, int] = {}
    for (raw,) in await session.execute(query):
        for tag in str(raw).split(","):
            tag = tag.strip().lower()
            if tag:
                counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


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
