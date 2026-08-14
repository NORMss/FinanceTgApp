from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, SessionDep
from app.api.schemas import (
    AccountCreate,
    AccountOut,
    CategoryCreate,
    CategoryDeleteOut,
    CategoryOut,
    CategoryUpdate,
    UserOut,
)
from app.models import CategoryKind
from app.repositories import accounts as accounts_repo
from app.repositories import categories as categories_repo
from app.repositories import transactions as tx_repo
from app.repositories import users as users_repo
from app.services import catalog as catalog_service
from app.util.money import to_minor

router = APIRouter(tags=["catalog"])


@router.get("/users", response_model=list[UserOut])
async def list_users(session: SessionDep, _: CurrentUser) -> list[UserOut]:
    return [UserOut.model_validate(user) for user in await users_repo.list_all(session)]


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    session: SessionDep,
    _: CurrentUser,
    include_archived: bool = Query(False),
) -> list[AccountOut]:
    accounts = await accounts_repo.list_all(session, include_archived=include_archived)
    return [AccountOut.model_validate(account) for account in accounts]


@router.post("/accounts", response_model=AccountOut, status_code=201)
async def create_account(
    payload: AccountCreate, session: SessionDep, _: CurrentUser
) -> AccountOut:
    account = await accounts_repo.create(
        session,
        name=payload.name,
        kind=payload.kind,
        currency=payload.currency.upper(),
        is_shared=payload.is_shared,
        owner_id=payload.owner_id,
        opening_balance_minor=to_minor(payload.opening_balance, payload.currency),
    )
    return AccountOut.model_validate(account)


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    session: SessionDep,
    _: CurrentUser,
    kind: CategoryKind | None = Query(None),
    include_archived: bool = Query(False),
) -> list[CategoryOut]:
    categories = await categories_repo.list_all(
        session, kind=kind, include_archived=include_archived
    )
    return [CategoryOut.model_validate(category) for category in categories]


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    payload: CategoryCreate, session: SessionDep, _: CurrentUser
) -> CategoryOut:
    try:
        category = await catalog_service.create_category(
            session,
            name=payload.name,
            kind=payload.kind,
            icon=payload.icon,
            parent_id=payload.parent_id,
            sort=payload.sort,
        )
    except catalog_service.CatalogError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return CategoryOut.model_validate(category)


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: str, payload: CategoryUpdate, session: SessionDep, _: CurrentUser
) -> CategoryOut:
    category = await categories_repo.get(session, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "категория не найдена")

    try:
        updated = await catalog_service.update_category(
            session,
            category,
            name=payload.name,
            icon=payload.icon,
            parent_id=payload.parent_id,
            # Явный null в теле запроса — «поднять на верхний уровень»
            move_to_root="parent_id" in payload.model_fields_set and payload.parent_id is None,
            sort=payload.sort,
            archived=payload.archived,
        )
    except catalog_service.CatalogError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return CategoryOut.model_validate(updated)


@router.delete("/categories/{category_id}", response_model=CategoryDeleteOut)
async def delete_category(
    category_id: str, session: SessionDep, _: CurrentUser
) -> CategoryDeleteOut:
    """Удаляет категорию или прячет её, если на неё ссылаются операции."""
    category = await categories_repo.get(session, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "категория не найдена")
    result = await catalog_service.delete_category(session, category)
    return CategoryDeleteOut(result=result)


@router.get("/categories/recent", response_model=list[str])
async def recent_categories(session: SessionDep, user: CurrentUser) -> list[str]:
    """ID последних использованных категорий — верхний ряд кнопок в форме ввода."""
    return await tx_repo.recent_category_ids(session, user.id)
