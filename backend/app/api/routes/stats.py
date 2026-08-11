from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, SessionDep
from app.api.periods import period_bounds
from app.api.schemas import (
    AccountBalanceOut,
    BalancesOut,
    SettleOut,
    SummaryOut,
    UserBalanceOut,
)
from app.repositories.transactions import TxFilter
from app.services import stats as stats_service
from app.util.money import format_amount

router = APIRouter(prefix="/stats", tags=["stats"])

PeriodDep = Annotated[tuple[datetime, datetime], Depends(period_bounds)]


@router.get("/summary", response_model=SummaryOut)
async def summary(session: SessionDep, _: CurrentUser, bounds: PeriodDep) -> SummaryOut:
    start, end = bounds
    data = await stats_service.period_summary(session, TxFilter(start=start, end=end))
    return SummaryOut(
        period_start=start,
        period_end=end,
        income_minor=data["income_minor"],
        expense_minor=data["expense_minor"],
        net_minor=data["net_minor"],
        count=data["count"],
        by_category=[asdict(item) for item in data["by_category"]],
        by_author=data["by_author"],
    )


@router.get("/balances", response_model=BalancesOut)
async def balances(session: SessionDep, _: CurrentUser) -> BalancesOut:
    items, total = await stats_service.account_balances(session)
    return BalancesOut(
        accounts=[AccountBalanceOut(**asdict(item)) for item in items],
        total_minor=total,
    )


@router.get("/settle", response_model=SettleOut)
async def settle(session: SessionDep, _: CurrentUser) -> SettleOut:
    """Кто кому должен по совместным тратам."""
    users = await stats_service.settle_up(session)
    creditor = max(users, key=lambda u: u.net_minor, default=None)
    debtor = min(users, key=lambda u: u.net_minor, default=None)

    hint = "Все в расчёте"
    if creditor and debtor and creditor.user_id != debtor.user_id and creditor.net_minor > 0:
        amount = min(creditor.net_minor, -debtor.net_minor)
        if amount > 0:
            hint = f"{debtor.name} → {creditor.name}: {format_amount(amount)}"

    return SettleOut(
        users=[UserBalanceOut(**asdict(item)) for item in users],
        hint=hint,
    )


@router.get("/monthly")
async def monthly(session: SessionDep, _: CurrentUser, bounds: PeriodDep) -> dict:
    """Матрица «месяц × категория» для сравнения периодов."""
    start, end = bounds
    return await stats_service.monthly_by_category(session, TxFilter(start=start, end=end))
