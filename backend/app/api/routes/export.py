from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from app.api.deps import CurrentUser, SessionDep
from app.api.filters import FiltersDep, build
from app.api.periods import period_bounds
from app.services import llm_export

router = APIRouter(prefix="/export", tags=["export"])

PeriodDep = Annotated[tuple[datetime, datetime], Depends(period_bounds)]


@router.get("/llm")
async def export_for_llm(
    session: SessionDep,
    _: CurrentUser,
    bounds: PeriodDep,
    filters: FiltersDep,
    fmt: Literal["md", "json"] = Query("md", alias="format"),
):
    """Агрегированный дамп для анализа языковой моделью.

    Фильтры те же, что у отчёта: если из отчёта скрыта ипотека, в дамп её тоже
    класть незачем — модель начнёт советовать сократить платёж по кредиту.
    """
    dump = await llm_export.build_dump(session, await build(session, filters, bounds))
    if fmt == "json":
        return dump
    return PlainTextResponse(llm_export.render_markdown(dump), media_type="text/markdown")
