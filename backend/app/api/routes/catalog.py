from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, SessionDep
from app.api.schemas import (
    AccountCreate,
    AccountOut,
    CategoryCreate,
    CategoryOut,
    UserOut,
)
from app.models import CategoryKind
from app.repositories import accounts as accounts_repo
from app.repositories import categories as categories_repo
from app.repositories import transactions as tx_repo
from app.repositories import users as users_repo
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
    category = await categories_repo.create(
        session,
        name=payload.name,
        kind=payload.kind,
        icon=payload.icon,
        parent_id=payload.parent_id,
        sort=payload.sort,
    )
    return CategoryOut.model_validate(category)


@router.get("/categories/recent", response_model=list[str])
async def recent_categories(session: SessionDep, user: CurrentUser) -> list[str]:
    """ID последних использованных категорий — верхний ряд кнопок в форме ввода."""
    return await tx_repo.recent_category_ids(session, user.id)
