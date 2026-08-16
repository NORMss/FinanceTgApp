from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, SessionDep
from app.api.periods import period_bounds
from app.api.schemas import (
    TransactionCreate,
    TransactionOut,
    TransactionPage,
    TransactionUpdate,
)
from app.models import TransactionType
from app.repositories import accounts as accounts_repo
from app.repositories import transactions as tx_repo
from app.repositories.transactions import TxFilter
from app.services import catalog as catalog_service
from app.services import ledger
from app.util.money import to_minor

router = APIRouter(prefix="/transactions", tags=["transactions"])

PeriodDep = Annotated[tuple[datetime, datetime], Depends(period_bounds)]


@router.get("", response_model=TransactionPage)
async def list_transactions(
    session: SessionDep,
    _: CurrentUser,
    bounds: PeriodDep,
    types: Annotated[list[TransactionType] | None, Query()] = None,
    category_ids: Annotated[list[str] | None, Query()] = None,
    account_ids: Annotated[list[str] | None, Query()] = None,
    author_ids: Annotated[list[str] | None, Query()] = None,
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> TransactionPage:
    start, end = bounds
    flt = TxFilter(
        start=start,
        end=end,
        types=types or [],
        # Выбранная категория тянет за собой подкатегории: «Продукты» — это и «Пятёрочка»
        category_ids=await catalog_service.expand_ids(session, category_ids or []),
        account_ids=account_ids or [],
        author_ids=author_ids or [],
        search=search,
    )
    items = await tx_repo.list_page(session, flt, limit=limit, offset=offset)
    return TransactionPage(
        items=[TransactionOut.model_validate(item) for item in items],
        total=await tx_repo.count(session, flt),
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=TransactionOut, status_code=201)
async def create_transaction(
    payload: TransactionCreate, session: SessionDep, user: CurrentUser
) -> TransactionOut:
    account_id = payload.account_id
    if not account_id:
        # Умолчание — свой личный счёт. Общий выбирают руками: трата с него делится
        # пополам, и делать это молча за человека нельзя
        default = await accounts_repo.default_for(session, user.id)
        if default is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "не указан счёт")
        account_id = default.id

    account = await accounts_repo.get(session, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "счёт не найден")

    try:
        amount_minor = to_minor(payload.amount, account.currency)
        splits = None
        if payload.splits is not None:
            splits = {
                user_id: to_minor(share, account.currency)
                for user_id, share in payload.splits.items()
            }
        elif payload.split_mode == "none":
            splits = {}

        tx = await ledger.create_transaction(
            session,
            author=user,
            tx_type=payload.type,
            amount_minor=amount_minor,
            account_id=account_id,
            counter_account_id=payload.counter_account_id,
            category_id=payload.category_id,
            occurred_at=payload.occurred_at,
            note=payload.note,
            tags=payload.tags,
            splits=splits,
        )
    except (ledger.LedgerError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return TransactionOut.model_validate(tx)


@router.get("/{tx_id}", response_model=TransactionOut)
async def get_transaction(tx_id: str, session: SessionDep, _: CurrentUser) -> TransactionOut:
    tx = await tx_repo.get(session, tx_id)
    if tx is None or tx.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "операция не найдена")
    return TransactionOut.model_validate(tx)


@router.patch("/{tx_id}", response_model=TransactionOut)
async def update_transaction(
    tx_id: str, payload: TransactionUpdate, session: SessionDep, _: CurrentUser
) -> TransactionOut:
    tx = await tx_repo.get(session, tx_id)
    if tx is None or tx.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "операция не найдена")

    sent = payload.model_fields_set
    currency = tx.currency

    try:
        splits: dict[str, int] | None | ledger.UnsetType = ledger.UNSET
        if payload.splits is not None:
            splits = {
                user_id: to_minor(share, currency) for user_id, share in payload.splits.items()
            }
        elif payload.split_mode == "none":
            splits = {}
        elif payload.split_mode == "auto":
            splits = None  # пересчитать по умолчанию

        updated = await ledger.update_transaction(
            session,
            tx,
            amount_minor=to_minor(payload.amount, currency) if payload.amount else None,
            occurred_at=payload.occurred_at,
            tx_type=payload.type,
            # Ключ прислали — применяем, даже если значение null: это «убрать категорию»
            category_id=payload.category_id if "category_id" in sent else ledger.UNSET,
            account_id=payload.account_id,
            counter_account_id=(
                payload.counter_account_id if "counter_account_id" in sent else ledger.UNSET
            ),
            note=payload.note,
            tags=payload.tags,
            splits=splits,
        )
    except (ledger.LedgerError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return TransactionOut.model_validate(updated)


@router.delete("/{tx_id}", status_code=204)
async def delete_transaction(tx_id: str, session: SessionDep, _: CurrentUser) -> None:
    tx = await tx_repo.get(session, tx_id)
    if tx is None or tx.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "операция не найдена")
    await ledger.delete_transaction(session, tx)
