"""Двусторонняя синхронизация журнала операций с Google Sheets."""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AppSetting,
    Category,
    CategoryKind,
    Transaction,
    TransactionType,
    TxSource,
)
from app.repositories import accounts as accounts_repo
from app.repositories import categories as categories_repo
from app.repositories import outbox as outbox_repo
from app.repositories import users as users_repo
from app.services import ledger
from app.sync.client import SheetsClient, SheetsUnavailable
from app.sync.mapping import HEADERS, SHEET_TRANSACTIONS, parse_row, row_hash, to_row
from app.util.dates import now

log = logging.getLogger(__name__)

LAST_COLUMN = chr(ord("A") + len(HEADERS) - 1)  # O при 15 колонках
DATA_RANGE = f"{SHEET_TRANSACTIONS}!A2:{LAST_COLUMN}"
KEY_LAST_PUSH = "sheets.last_push_at"
KEY_LAST_ERROR = "sheets.last_error"


@dataclass(slots=True)
class PushResult:
    updated: int = 0
    appended: int = 0


@dataclass(slots=True)
class PullResult:
    applied: int = 0
    created: int = 0
    skipped: int = 0


async def _set_state(session: AsyncSession, key: str, value: str | None) -> None:
    setting = await session.get(AppSetting, key)
    if setting is None:
        session.add(AppSetting(key=key, value=value or ""))
    else:
        setting.value = value or ""


async def get_state(session: AsyncSession, key: str) -> str | None:
    setting = await session.get(AppSetting, key)
    return setting.value if setting and setting.value else None


async def ensure_layout(client: SheetsClient) -> None:
    """Создаёт лист и шапку, если их ещё нет. Идемпотентно."""
    titles = await client.sheet_titles()
    if SHEET_TRANSACTIONS not in titles:
        await client.create_sheet(SHEET_TRANSACTIONS)

    header = await client.get_values(f"{SHEET_TRANSACTIONS}!A1:{LAST_COLUMN}1")
    if not header or header[0][: len(HEADERS)] != HEADERS:
        await client.update_values(
            [(f"{SHEET_TRANSACTIONS}!A1:{LAST_COLUMN}1", [HEADERS])]
        )


async def _row_index(client: SheetsClient) -> dict[str, int]:
    """Карта «id операции -> номер строки». Один дешёвый запрос на одну колонку."""
    column = await client.get_values(f"{SHEET_TRANSACTIONS}!A2:A")
    return {
        str(row[0]).strip(): index
        for index, row in enumerate(column, start=2)
        if row and str(row[0]).strip()
    }


async def _name_maps(session: AsyncSession) -> tuple[dict, dict, dict]:
    accounts = {
        account.id: account.name
        for account in await accounts_repo.list_all(session, include_archived=True)
    }
    categories = {
        category.id: category.name
        for category in await categories_repo.list_all(session, include_archived=True)
    }
    users = {user.id: user.display_name for user in await users_repo.list_all(session)}
    return accounts, categories, users


async def push_pending(session: AsyncSession, client: SheetsClient) -> PushResult:
    """Выгружает накопленные изменения. Ошибка оставляет записи в очереди на следующий заход."""
    items = await outbox_repo.take_pending(session, limit=300)
    if not items:
        return PushResult()

    tx_ids = list({item.entity_id for item in items if item.entity == ledger.ENTITY})
    result = PushResult()
    if tx_ids:
        try:
            await ensure_layout(client)
            result = await _push_transactions(session, client, tx_ids)
        except SheetsUnavailable as exc:
            await outbox_repo.mark_failed(session, items, str(exc))
            await _set_state(session, KEY_LAST_ERROR, str(exc))
            log.warning("выгрузка в Sheets не удалась: %s", exc)
            return PushResult()

    await outbox_repo.mark_done(session, items)
    await _set_state(session, KEY_LAST_PUSH, now().isoformat())
    await _set_state(session, KEY_LAST_ERROR, None)
    return result


async def _push_transactions(
    session: AsyncSession, client: SheetsClient, tx_ids: list[str]
) -> PushResult:
    rows = await session.execute(select(Transaction).where(Transaction.id.in_(tx_ids)))
    transactions = list(rows.scalars())
    if not transactions:
        return PushResult()

    account_names, category_names, user_names = await _name_maps(session)
    index = await _row_index(client)

    updates: list[tuple[str, list[list]]] = []
    appends: list[list] = []
    for tx in sorted(transactions, key=lambda item: item.id):
        row = to_row(
            tx,
            account_names=account_names,
            category_names=category_names,
            user_names=user_names,
        )
        line = index.get(tx.id)
        if line:
            updates.append((f"{SHEET_TRANSACTIONS}!A{line}:{LAST_COLUMN}{line}", [row]))
        else:
            appends.append(row)

    await client.update_values(updates)
    await client.append_values(f"{SHEET_TRANSACTIONS}!A1", appends)
    return PushResult(updated=len(updates), appended=len(appends))


async def full_resync(session: AsyncSession, client: SheetsClient) -> PushResult:
    """Полная перезаливка журнала в таблицу — на случай, если лист испортили руками."""
    await ensure_layout(client)
    rows = await session.execute(select(Transaction.id).order_by(Transaction.id))
    all_ids = [row for row in rows.scalars()]

    total = PushResult()
    for start in range(0, len(all_ids), 300):
        chunk = all_ids[start : start + 300]
        partial = await _push_transactions(session, client, chunk)
        total.updated += partial.updated
        total.appended += partial.appended
    await _set_state(session, KEY_LAST_PUSH, now().isoformat())
    return total


async def _ensure_category(session: AsyncSession, name: str, kind: CategoryKind) -> Category | None:
    if not name.strip():
        return None
    existing = await categories_repo.get_by_name(session, name, kind=kind)
    if existing is not None:
        return existing
    log.info("создаю категорию из таблицы: %s", name)
    return await categories_repo.create(session, name=name, kind=kind)


async def pull_edits(session: AsyncSession, client: SheetsClient) -> PullResult:
    """Забирает правки, сделанные человеком прямо в таблице.

    Строка считается изменённой, если пересчитанный хеш её редактируемых ячеек не совпал
    с сохранённым в колонке sync_hash. Строки без id — это новые записи, добавленные руками.
    """
    await ensure_layout(client)
    rows = await client.get_values(DATA_RANGE)
    if not rows:
        return PullResult()

    users = await users_repo.list_all(session)
    default_author = next((user for user in users if user.is_active), None)
    shared = await accounts_repo.get_shared(session)
    result = PullResult()

    for values in rows:
        view = parse_row(values)
        if view is None:
            continue

        if not view.id:
            if view.amount_minor and default_author and shared:
                kind = (
                    CategoryKind.INCOME
                    if view.tx_type == TransactionType.INCOME
                    else CategoryKind.EXPENSE
                )
                category = await _ensure_category(session, view.category, kind)
                await ledger.create_transaction(
                    session,
                    author=default_author,
                    tx_type=view.tx_type or TransactionType.EXPENSE,
                    amount_minor=view.amount_minor,
                    account_id=shared.id,
                    category_id=category.id if category else None,
                    occurred_at=view.occurred_at,
                    note=view.note,
                    tags=view.tags,
                    source=TxSource.SHEET,
                )
                result.created += 1
            else:
                result.skipped += 1
            continue

        if row_hash(values) == view.sync_hash:
            continue  # строку никто не трогал

        tx = await session.get(Transaction, view.id)
        if tx is None:
            result.skipped += 1
            continue

        if view.deleted and tx.deleted_at is None:
            await ledger.delete_transaction(session, tx)
            result.applied += 1
            continue

        kind = (
            CategoryKind.INCOME if tx.type == TransactionType.INCOME else CategoryKind.EXPENSE
        )
        category = await _ensure_category(session, view.category, kind)
        await ledger.update_transaction(
            session,
            tx,
            amount_minor=view.amount_minor,
            occurred_at=view.occurred_at,
            category_id=category.id if category else "",
            note=view.note,
            tags=view.tags,
        )
        result.applied += 1

    return result


async def status(session: AsyncSession) -> dict:
    last_push = await get_state(session, KEY_LAST_PUSH)
    return {
        "enabled": settings.sheets_enabled,
        "configured": settings.sheets_ready,
        "pending": await outbox_repo.pending_count(session),
        "last_push_at": datetime.fromisoformat(last_push) if last_push else None,
        "last_error": await get_state(session, KEY_LAST_ERROR),
        "spreadsheet_url": (
            SheetsClient.from_settings().spreadsheet_url if settings.google_spreadsheet_id else None
        ),
    }
