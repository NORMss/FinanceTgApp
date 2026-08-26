"""Агрегаты для отчётов: итоги за период, остатки по счетам, взаиморасчёты."""

from dataclasses import dataclass, field, replace
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, CategoryKind, TransactionType
from app.repositories import accounts as accounts_repo
from app.repositories import budgets as budgets_repo
from app.repositories import categories as categories_repo
from app.repositories import transactions as tx_repo
from app.repositories import users as users_repo
from app.repositories.transactions import TxFilter
from app.util.dates import add_months, as_utc, day_start, previous_bounds

# Сколько крупнейших трат и повторяющихся строк показывать. Пять и восемь —
# не круглые числа ради красоты: длиннее списка человек уже не читает, а месячный
# ритуал в docs/finance.md просит найти одну категорию, а не десять.
TOP_LARGEST = 5
TOP_REPEATED = 8


@dataclass(slots=True)
class CategoryTotal:
    category_id: str | None
    name: str
    icon: str
    amount_minor: int  # вместе с подкатегориями
    count: int
    share: float  # доля в общих тратах периода, 0..1
    parent_id: str | None = None
    own_minor: int = 0  # потрачено прямо на эту категорию, без детей
    # Столько же ушло в прошлом периоде. Заполняется только при compare=True
    previous_minor: int = 0
    # Месячный лимит. Ноль — лимита нет; отдаётся только для месячных периодов
    limit_minor: int = 0


@dataclass(slots=True)
class TxBrief:
    """Операция в отчёте — ровно те поля, которые рисует строка списка."""

    id: str
    occurred_at: datetime
    amount_minor: int
    category_id: str | None
    author_id: str
    note: str


@dataclass(slots=True)
class RepeatedSpend:
    note: str
    count: int
    total_minor: int


@dataclass(slots=True)
class PeriodTotals:
    """Итоги периода без разбивки — этим сравнивают два периода между собой."""

    income_minor: int = 0
    expense_minor: int = 0
    net_minor: int = 0


@dataclass(slots=True)
class AccountBalance:
    account_id: str
    name: str
    currency: str
    is_shared: bool
    balance_minor: int


@dataclass(slots=True)
class UserBalance:
    user_id: str
    name: str
    paid_minor: int
    owed_minor: int
    net_minor: int  # >0 — человеку должны, <0 — должен он


@dataclass(slots=True)
class MonthlyTrend:
    months: list[str] = field(default_factory=list)
    expense: list[int] = field(default_factory=list)
    income: list[int] = field(default_factory=list)
    categories: list[dict] = field(default_factory=list)


# --- фильтры ---------------------------------------------------------------


def _with_types(flt: TxFilter, types: list[TransactionType]) -> TxFilter:
    return replace(flt, types=types)


def _by_kind(
    catalog: dict[str, Category], ids: list[str], kind: CategoryKind
) -> list[str]:
    """Оставляет из списка категорий только те, что относятся к нужной стороне отчёта.

    Без этого фильтр «покажи Продукты» обнулял доходы: доходные операции лежат
    в доходных категориях, ни одна из них в расходный список не попадает, и сумма
    доходов честно получалась нулевой, а сальдо — отрицательным при живой зарплате.
    Человек же имеет в виду «ограничь расходы Продуктами», а доходы не трогай.

    Неизвестные идентификаторы считаем расходными: расходы — основная сторона
    отчёта, и фильтр по выдуманной категории должен показать ноль, а не всё подряд.
    """
    known = [item for item in ids if item in catalog]
    unknown = [item for item in ids if item not in catalog]
    picked = [item for item in known if catalog[item].kind == kind]
    return picked + unknown if kind == CategoryKind.EXPENSE else picked


def _side(
    flt: TxFilter, catalog: dict[str, Category], kind: CategoryKind, tx_type: TransactionType
) -> TxFilter:
    """Фильтр одной стороны отчёта — расходной или доходной."""
    return replace(
        flt,
        types=[tx_type],
        category_ids=_by_kind(catalog, flt.category_ids, kind),
        exclude_category_ids=_by_kind(catalog, flt.exclude_category_ids, kind),
    )


def _without_exclusions(flt: TxFilter) -> TxFilter:
    return replace(flt, exclude_category_ids=[], exclude_uncategorized=False, exclude_tags=[])


def has_exclusions(flt: TxFilter) -> bool:
    return bool(flt.exclude_category_ids or flt.exclude_uncategorized or flt.exclude_tags)


def _is_whole_month(start: datetime | None, end: datetime | None) -> bool:
    """Совпадает ли период ровно с календарным месяцем.

    От этого зависит, показывать ли лимиты: лимит месячный, и «17 % от лимита»
    за неделю — цифра, из которой нельзя сделать ни одного вывода.
    """
    if start is None or end is None:
        return False
    begin = as_utc(start)
    return (
        begin.day == 1
        and begin == day_start(begin.date())
        and as_utc(end) == day_start(add_months(begin.date(), 1))
    )


# --- сводка ----------------------------------------------------------------


async def period_summary(
    session: AsyncSession, flt: TxFilter, *, compare: bool = False
) -> dict:
    """Всё, что рисует экран отчёта, одним запросом к базе данных.

    Собирать это в одном месте, а не пятью ручками, — решение про клиент, а не про
    сервер: экран отчёта перерисовывается целиком при каждом движении фильтра, и пять
    независимых запросов давали бы пять моментов, когда половина цифр уже новая,
    а половина ещё старая.
    """
    catalog = {c.id: c for c in await categories_repo.list_all(session, include_archived=True)}

    expense_flt = _side(flt, catalog, CategoryKind.EXPENSE, TransactionType.EXPENSE)
    income_flt = _side(flt, catalog, CategoryKind.INCOME, TransactionType.INCOME)

    expense = await _total(session, expense_flt)
    income = await _total(session, income_flt)

    limits = await budgets_repo.by_category(session) if _is_whole_month(flt.start, flt.end) else {}

    rows = await tx_repo.totals_by_category(session, expense_flt)
    by_category = _build_category_tree(rows, catalog, expense)
    income_rows = await tx_repo.totals_by_category(session, income_flt)
    by_income_category = _build_category_tree(income_rows, catalog, income)

    authors = await tx_repo.totals_by_author(session, expense_flt)
    spenders = await tx_repo.spend_by_user(session, expense_flt)
    users = {u.id: u.display_name for u in await users_repo.list_all(session)}

    # Скрытое считаем только когда есть что скрывать: лишний агрегат на каждый
    # запрос отчёта незачем, а без исключений ответ заведомо нулевой
    excluded_minor = 0
    excluded_count = 0
    if has_exclusions(flt):
        bare = _without_exclusions(expense_flt)
        excluded_minor = await _total(session, bare) - expense
        excluded_count = await tx_repo.count(session, bare) - await tx_repo.count(
            session, expense_flt
        )

    previous: PeriodTotals | None = None
    if compare:
        previous = await _compare_with_previous(session, flt, catalog, by_category)

    if limits:
        for item in by_category:
            item.limit_minor = limits.get(item.category_id or "", 0)

    largest = [
        _brief(tx) for tx in await tx_repo.largest(session, expense_flt, limit=TOP_LARGEST)
    ]
    repeated = [
        RepeatedSpend(note=note, count=count, total_minor=total)
        for note, count, total in await tx_repo.repeated_notes(
            session, expense_flt, limit=TOP_REPEATED
        )
    ]

    return {
        "income_minor": income,
        "expense_minor": expense,
        "net_minor": income - expense,
        # Операции, попавшие в цифры выше. Переводы сюда не входят: отчёт их не
        # показывает, а «данных нет» при одних переводах — честная подпись
        "count": await tx_repo.count(session, expense_flt)
        + await tx_repo.count(session, income_flt),
        "excluded_minor": excluded_minor,
        "excluded_count": excluded_count,
        "by_category": by_category,
        "by_income_category": by_income_category,
        "by_author": _named(authors, users),
        "by_spender": _named(spenders, users),
        "largest": largest,
        "repeated": repeated,
        "previous": previous,
    }


async def _total(session: AsyncSession, flt: TxFilter) -> int:
    """Сумма по одному типу операций. Фильтр обязан быть уже сужен до типа."""
    totals = await tx_repo.totals_by_type(session, flt)
    return sum(totals.values())


def _brief(tx) -> TxBrief:
    return TxBrief(
        id=tx.id,
        occurred_at=tx.occurred_at,
        amount_minor=tx.amount_minor,
        category_id=tx.category_id,
        author_id=tx.author_id,
        note=tx.note,
    )


def _named(totals: dict[str, int], users: dict[str, str]) -> list[dict]:
    return [
        {"user_id": user_id, "name": users.get(user_id, "?"), "amount_minor": amount}
        for user_id, amount in sorted(totals.items(), key=lambda i: i[1], reverse=True)
    ]


async def _compare_with_previous(
    session: AsyncSession,
    flt: TxFilter,
    catalog: dict[str, Category],
    by_category: list[CategoryTotal],
) -> PeriodTotals | None:
    """Те же цифры за предыдущий период — и та же дельта на каждой категории.

    Сравнивать «месяц с месяцем» приходится календарно, а не «минус тридцать дней»:
    в феврале двадцать восемь дней, и окно фиксированной длины сдвинуло бы границу
    внутрь января, отчего февраль всегда выглядел бы дешевле января.
    """
    if flt.start is None or flt.end is None:
        return None
    bounds = previous_bounds(flt.start, flt.end)
    if bounds is None:
        return None

    start, end = bounds
    shifted = replace(flt, start=start, end=end)
    expense_flt = _side(shifted, catalog, CategoryKind.EXPENSE, TransactionType.EXPENSE)
    income_flt = _side(shifted, catalog, CategoryKind.INCOME, TransactionType.INCOME)

    expense = await _total(session, expense_flt)
    income = await _total(session, income_flt)

    rows = await tx_repo.totals_by_category(session, expense_flt)
    previous_tree = {
        item.category_id: item.amount_minor
        for item in _build_category_tree(rows, catalog, expense)
    }
    for item in by_category:
        item.previous_minor = previous_tree.get(item.category_id, 0)

    return PeriodTotals(
        income_minor=income, expense_minor=expense, net_minor=income - expense
    )


def _build_category_tree(
    rows: list[tuple[str | None, int, int]],
    catalog: dict[str, Category],
    expense_total: int,
) -> list[CategoryTotal]:
    """Плоский список сумм превращает в дерево, свёрнутое в родителей.

    В отчёте нужны обе цифры: «на супермаркеты ушло 12 000» и из чего они сложились.
    Поэтому родитель показывает сумму вместе с детьми (`amount_minor`), а `own_minor`
    хранит то, что записали прямо на него, без разбивки. Порядок плоский, но осмысленный:
    родитель, сразу за ним его подкатегории — клиенту остаётся только сделать отступ.
    """
    own: dict[str | None, tuple[int, int]] = {
        category_id: (amount, count) for category_id, amount, count in rows
    }

    totals: dict[str | None, int] = {}
    counts: dict[str | None, int] = {}
    for category_id, (amount, count) in own.items():
        category = catalog.get(category_id or "")
        keys = [category_id]
        if category is not None and category.parent_id:
            keys.append(category.parent_id)
        for key in keys:
            totals[key] = totals.get(key, 0) + amount
            counts[key] = counts.get(key, 0) + count

    def node(category_id: str | None) -> CategoryTotal:
        category = catalog.get(category_id or "")
        amount = totals.get(category_id, 0)
        return CategoryTotal(
            category_id=category_id,
            name=category.name if category else "Без категории",
            icon=category.icon if category else "",
            amount_minor=amount,
            count=counts.get(category_id, 0),
            share=(amount / expense_total) if expense_total else 0.0,
            parent_id=category.parent_id if category else None,
            own_minor=own.get(category_id, (0, 0))[0],
        )

    roots = [
        category_id
        for category_id in totals
        if not (category_id and catalog.get(category_id) and catalog[category_id].parent_id)
    ]
    result: list[CategoryTotal] = []
    for root_id in sorted(roots, key=lambda key: totals.get(key, 0), reverse=True):
        result.append(node(root_id))
        # У «Без категории» детей быть не может. Без этой проверки под неё попадали
        # все корневые категории разом — у них parent_id тоже None, — и каждая
        # выводилась в отчёте дважды, а сумма долей уходила далеко за сто процентов
        children = (
            []
            if root_id is None
            else [
                category_id
                for category_id in own
                if category_id
                and catalog.get(category_id)
                and catalog[category_id].parent_id == root_id
            ]
        )
        result.extend(
            node(child_id)
            for child_id in sorted(children, key=lambda key: own[key][0], reverse=True)
        )
    return result


# --- остатки и взаиморасчёты ------------------------------------------------


async def account_balances(session: AsyncSession) -> tuple[list[AccountBalance], int]:
    accounts = await accounts_repo.list_all(session)
    deltas = await tx_repo.account_deltas(session)
    balances = [
        AccountBalance(
            account_id=account.id,
            name=account.name,
            currency=account.currency,
            is_shared=account.is_shared,
            balance_minor=account.opening_balance_minor + deltas.get(account.id, 0),
        )
        for account in accounts
    ]
    # Складывать разные валюты бессмысленно, поэтому в итог идёт только базовая
    total = sum(b.balance_minor for b in balances)
    return balances, total


async def settle_up(session: AsyncSession, flt: TxFilter | None = None) -> list[UserBalance]:
    """Кто кому должен по операциям с общего счёта.

    net = (сколько человек фактически заплатил) - (сколько на него начислено по долям).
    Переводы между личными счетами разных людей считаются погашением долга:
    отправитель уменьшает свой минус, получатель — свой плюс.
    """
    flt = flt or TxFilter()
    paid = await tx_repo.paid_by_user(session, flt)
    owed = await tx_repo.owed_by_user(session, flt)

    users = await users_repo.list_all(session)
    accounts = {a.id: a for a in await accounts_repo.list_all(session, include_archived=True)}

    settlements: dict[str, int] = {}
    transfer_filter = _with_types(flt, [TransactionType.TRANSFER])
    for tx in await tx_repo.list_page(session, transfer_filter, limit=10_000):
        source = accounts.get(tx.account_id)
        target = accounts.get(tx.counter_account_id or "")
        if not source or not target or not source.owner_id or not target.owner_id:
            continue
        if source.owner_id == target.owner_id:
            continue
        settlements[source.owner_id] = settlements.get(source.owner_id, 0) + tx.amount_minor
        settlements[target.owner_id] = settlements.get(target.owner_id, 0) - tx.amount_minor

    return [
        UserBalance(
            user_id=user.id,
            name=user.display_name,
            paid_minor=paid.get(user.id, 0),
            owed_minor=owed.get(user.id, 0),
            net_minor=paid.get(user.id, 0) - owed.get(user.id, 0) + settlements.get(user.id, 0),
        )
        for user in users
    ]


# --- динамика ---------------------------------------------------------------


async def monthly_by_category(session: AsyncSession, flt: TxFilter) -> dict:
    """Матрица «месяц × категория» — для сравнения месяцев и для дампа в LLM."""
    expense_filter = _with_types(flt, [TransactionType.EXPENSE])
    rows = await tx_repo.totals_by_month_category(session, expense_filter)
    catalog = {c.id: c.name for c in await categories_repo.list_all(session, include_archived=True)}

    months = sorted({month for month, _, _ in rows})
    matrix: dict[str, dict[str, int]] = {}
    for month, category_id, amount in rows:
        name = catalog.get(category_id or "", "Без категории")
        matrix.setdefault(name, {})[month] = amount

    return {"months": months, "categories": matrix}


async def monthly_trend(session: AsyncSession, flt: TxFilter, *, top: int = 6) -> MonthlyTrend:
    """Помесячные столбики для графика: итоги и разбивка по крупнейшим категориям.

    Категории сворачиваются в корневые: на графике шириной в экран телефона
    «Продукты · Пятёрочка» и «Продукты · Магнит» — две линии там, где человеку
    нужна одна. Разбивка по магазинам осталась в списке отчёта, здесь она мешает.
    """
    catalog = {c.id: c for c in await categories_repo.list_all(session, include_archived=True)}

    months: list[str] = []
    expense: dict[str, int] = {}
    income: dict[str, int] = {}
    for month, tx_type, amount in await tx_repo.totals_by_month_type(session, flt):
        if tx_type == TransactionType.EXPENSE.value:
            expense[month] = expense.get(month, 0) + amount
        elif tx_type == TransactionType.INCOME.value:
            income[month] = income.get(month, 0) + amount
    months = sorted(set(expense) | set(income))

    expense_filter = _with_types(flt, [TransactionType.EXPENSE])
    per_category: dict[str, dict[str, int]] = {}
    for month, category_id, amount in await tx_repo.totals_by_month_category(
        session, expense_filter
    ):
        category = catalog.get(category_id or "")
        root = (category.parent_id or category.id) if category else ""
        bucket = per_category.setdefault(root, {})
        bucket[month] = bucket.get(month, 0) + amount

    ranked = sorted(per_category.items(), key=lambda item: sum(item[1].values()), reverse=True)
    categories = [
        {
            "category_id": root or None,
            "name": catalog[root].name if root in catalog else "Без категории",
            "icon": catalog[root].icon if root in catalog else "",
            "amounts": [values.get(month, 0) for month in months],
        }
        for root, values in ranked[:top]
    ]

    return MonthlyTrend(
        months=months,
        expense=[expense.get(month, 0) for month in months],
        income=[income.get(month, 0) for month in months],
        categories=categories,
    )
