"""Агрегаты для отчётов: итоги за период, остатки по счетам, взаиморасчёты."""

from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TransactionType
from app.repositories import accounts as accounts_repo
from app.repositories import categories as categories_repo
from app.repositories import transactions as tx_repo
from app.repositories import users as users_repo
from app.repositories.transactions import TxFilter


@dataclass(slots=True)
class CategoryTotal:
    category_id: str | None
    name: str
    icon: str
    amount_minor: int
    count: int
    share: float  # доля в общих тратах периода, 0..1


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


async def period_summary(session: AsyncSession, flt: TxFilter) -> dict:
    totals = await tx_repo.totals_by_type(session, flt)
    income = totals.get(TransactionType.INCOME.value, 0)
    expense = totals.get(TransactionType.EXPENSE.value, 0)

    expense_filter = _with_types(flt, [TransactionType.EXPENSE])
    rows = await tx_repo.totals_by_category(session, expense_filter)
    catalog = {c.id: c for c in await categories_repo.list_all(session, include_archived=True)}
    by_category = [
        CategoryTotal(
            category_id=category_id,
            name=catalog[category_id].name if category_id in catalog else "Без категории",
            icon=catalog[category_id].icon if category_id in catalog else "",
            amount_minor=amount,
            count=count,
            share=(amount / expense) if expense else 0.0,
        )
        for category_id, amount, count in rows
    ]

    authors = await tx_repo.totals_by_author(session, expense_filter)
    users = {u.id: u.display_name for u in await users_repo.list_all(session)}

    return {
        "income_minor": income,
        "expense_minor": expense,
        "net_minor": income - expense,
        "count": await tx_repo.count(session, flt),
        "by_category": by_category,
        "by_author": [
            {"user_id": user_id, "name": users.get(user_id, "?"), "amount_minor": amount}
            for user_id, amount in sorted(authors.items(), key=lambda i: i[1], reverse=True)
        ],
    }


def _with_types(flt: TxFilter, types: list[TransactionType]) -> TxFilter:
    return replace(flt, types=types)


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
