import logging
from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.deps import CurrentUser, SessionDep
from app.api.filters import FiltersDep, build
from app.api.periods import period_bounds
from app.api.schemas import (
    AccountBalanceOut,
    BalancesOut,
    SettleOut,
    SummaryOut,
    TrendOut,
    UserBalanceOut,
)
from app.repositories.transactions import TxFilter
from app.services import report_text
from app.services import stats as stats_service
from app.util.money import format_amount

log = logging.getLogger(__name__)

router = APIRouter(prefix="/stats", tags=["stats"])

PeriodDep = Annotated[tuple[datetime, datetime], Depends(period_bounds)]


@router.get("/summary", response_model=SummaryOut)
async def summary(
    session: SessionDep,
    _: CurrentUser,
    bounds: PeriodDep,
    filters: FiltersDep,
    compare: bool = Query(False, description="добавить итоги предыдущего периода"),
) -> SummaryOut:
    """Итоги за период. Фильтры те же, что у списка операций, — иначе отчёт
    показывал бы одно, а история по тем же условиям другое."""
    start, end = bounds
    flt = await build(session, filters, bounds)
    data = await stats_service.period_summary(session, flt, compare=compare)
    return SummaryOut(
        period_start=start,
        period_end=end,
        income_minor=data["income_minor"],
        expense_minor=data["expense_minor"],
        net_minor=data["net_minor"],
        count=data["count"],
        excluded_minor=data["excluded_minor"],
        excluded_count=data["excluded_count"],
        by_category=[asdict(item) for item in data["by_category"]],
        by_income_category=[asdict(item) for item in data["by_income_category"]],
        by_author=data["by_author"],
        by_spender=data["by_spender"],
        largest=[asdict(item) for item in data["largest"]],
        repeated=[asdict(item) for item in data["repeated"]],
        previous=asdict(data["previous"]) if data["previous"] else None,
    )


@router.post("/share", status_code=202)
async def share(
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    bounds: PeriodDep,
    filters: FiltersDep,
) -> dict:
    """Отправляет сводку текущего отчёта в личный чат с ботом.

    Отчёт, который можно обсудить, полезнее отчёта, который можно только посмотреть:
    цифра, оставшаяся в переписке, возвращается к разговору через неделю, а экран
    приложения закрывается и забывается.

    Уходит именно тому, кто нажал: рассылать второму участнику чужой срез с чужими
    исключениями — не то, о чём просили нажатием кнопки «отправить себе».
    """
    bot = getattr(request.app.state, "bot", None)
    if bot is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "бот выключен — отправлять сводку некому"
        )

    start, end = bounds
    flt = await build(session, filters, bounds)
    data = await stats_service.period_summary(session, flt, compare=True)
    try:
        await bot.send_message(user.telegram_id, report_text.render(data, start, end))
    except Exception as exc:  # noqa: BLE001 — сеть, 429, заблокированный бот
        log.warning("сводка не ушла в чат %s: %s", user.id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Telegram не принял сообщение, попробуйте позже"
        ) from exc
    return {"sent": True}


@router.get("/trend", response_model=TrendOut)
async def trend(
    session: SessionDep,
    _: CurrentUser,
    bounds: PeriodDep,
    filters: FiltersDep,
    top: int = Query(6, ge=1, le=12, description="сколько категорий показать на графике"),
) -> TrendOut:
    """Помесячные столбики за период — расходы, доходы и крупнейшие категории.

    Период здесь задают широкий («Год», «Всё время»): график из одного столбика
    ничего не сравнивает.
    """
    flt = await build(session, filters, bounds)
    data = await stats_service.monthly_trend(session, flt, top=top)
    return TrendOut(**asdict(data))


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
