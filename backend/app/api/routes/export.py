from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from app.api.deps import CurrentUser, SessionDep
from app.api.periods import period_bounds
from app.repositories.transactions import TxFilter
from app.services import llm_export

router = APIRouter(prefix="/export", tags=["export"])

PeriodDep = Annotated[tuple[datetime, datetime], Depends(period_bounds)]


@router.get("/llm")
async def export_for_llm(
    session: SessionDep,
    _: CurrentUser,
    bounds: PeriodDep,
    fmt: Literal["md", "json"] = Query("md", alias="format"),
):
    """Агрегированный дамп для анализа языковой моделью."""
    start, end = bounds
    dump = await llm_export.build_dump(session, TxFilter(start=start, end=end))
    if fmt == "json":
        return dump
    return PlainTextResponse(llm_export.render_markdown(dump), media_type="text/markdown")
