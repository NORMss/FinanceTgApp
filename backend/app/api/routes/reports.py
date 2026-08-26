"""Настройки отчёта: месячные лимиты, сохранённые виды, справочник меток.

Всё это не цифры отчёта, а то, из чего он собирается, — поэтому отдельный модуль,
а не довесок к `/stats`.
"""

import json

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.api.schemas import (
    BudgetOut,
    BudgetUpdate,
    ReportViewCreate,
    ReportViewOut,
    TagOut,
)
from app.repositories import budgets as budgets_repo
from app.repositories import categories as categories_repo
from app.repositories import report_views as views_repo
from app.repositories import transactions as tx_repo
from app.util.money import to_minor

router = APIRouter(tags=["reports"])

# Потолок на размер сохранённого вида. Вид — это горстка идентификаторов; килобайт
# с запасом покрывает даже отчёт, где скрыта половина справочника
MAX_PAYLOAD = 4096
MAX_VIEWS = 20


@router.get("/budgets", response_model=list[BudgetOut])
async def list_budgets(session: SessionDep, _: CurrentUser) -> list[BudgetOut]:
    return [
        BudgetOut(category_id=item.category_id, limit_minor=item.limit_minor)
        for item in await budgets_repo.list_all(session)
    ]


@router.put("/budgets/{category_id}", response_model=BudgetOut)
async def set_budget(
    category_id: str, payload: BudgetUpdate, session: SessionDep, _: CurrentUser
) -> BudgetOut:
    """Задать месячный лимит категории.

    Лимит общий на семью, а не личный: «на продукты 25 000 в месяц» — это
    договорённость двоих, и два её экземпляра однажды разойдутся.
    """
    category = await categories_repo.get(session, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "категория не найдена")

    try:
        limit_minor = to_minor(payload.limit)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if limit_minor < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "лимит не может быть отрицательным")

    budget = await budgets_repo.upsert(session, category_id=category_id, limit_minor=limit_minor)
    return BudgetOut(category_id=budget.category_id, limit_minor=budget.limit_minor)


@router.delete("/budgets/{category_id}", status_code=204)
async def drop_budget(category_id: str, session: SessionDep, _: CurrentUser) -> None:
    """Снять лимит. Отсутствие лимита и лимит в ноль — разные вещи: второе означает
    «на это не тратим», и полоса в отчёте станет красной с первой же траты."""
    if not await budgets_repo.remove(session, category_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "лимита на этой категории нет")


@router.get("/report-views", response_model=list[ReportViewOut])
async def list_views(session: SessionDep, user: CurrentUser) -> list[ReportViewOut]:
    return [_view_out(item) for item in await views_repo.list_for(session, user.id)]


@router.post("/report-views", response_model=ReportViewOut, status_code=201)
async def save_view(
    payload: ReportViewCreate, session: SessionDep, user: CurrentUser
) -> ReportViewOut:
    """Сохранить текущий набор фильтров под именем.

    Виды личные: один смотрит «сколько мы тратим без ипотеки», второму интереснее
    «только общий счёт», и навязывать друг другу набор галочек незачем.
    """
    body = json.dumps(payload.payload, ensure_ascii=False, separators=(",", ":"))
    if len(body) > MAX_PAYLOAD:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "слишком большой набор фильтров")

    existing = await views_repo.list_for(session, user.id)
    known = {item.name.casefold() for item in existing}
    if len(existing) >= MAX_VIEWS and payload.name.strip().casefold() not in known:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"видов уже {MAX_VIEWS} — удалите ненужный, чтобы сохранить новый",
        )

    view = await views_repo.save(
        session, owner_id=user.id, name=payload.name, payload=body, sort=payload.sort
    )
    return _view_out(view)


@router.delete("/report-views/{view_id}", status_code=204)
async def drop_view(view_id: str, session: SessionDep, user: CurrentUser) -> None:
    view = await views_repo.get(session, view_id)
    # Чужой вид отдаём как несуществующий: участников двое, и сообщение
    # «это не ваш вид» ничего не добавляет, кроме подтверждения, что он есть
    if view is None or view.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "вид не найден")
    await views_repo.remove(session, view)


@router.get("/tags", response_model=list[TagOut])
async def list_tags(session: SessionDep, _: CurrentUser) -> list[TagOut]:
    """Встречавшиеся метки, самые частые первыми — из них собирается фильтр."""
    return [TagOut(name=name, count=count) for name, count in await tx_repo.known_tags(session)]


def _view_out(view) -> ReportViewOut:
    try:
        payload = json.loads(view.payload)
    except ValueError:
        # Строку в базу кладём только мы, но если она всё же испортилась — отдать
        # пустой вид честнее, чем уронить весь список пятисоткой
        payload = {}
    return ReportViewOut(
        id=view.id, name=view.name, payload=payload if isinstance(payload, dict) else {},
        sort=view.sort,
    )
