from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.api.schemas import SyncStatusOut
from app.config import settings
from app.sync import service as sync_service
from app.sync.client import SheetsClient, SheetsUnavailable
from app.sync.scheduler import resync_now

router = APIRouter(prefix="/sync", tags=["sync"])


def _require_sheets() -> None:
    if not settings.sheets_ready:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "синхронизация не настроена: проверь SHEETS_ENABLED, ID таблицы и файл ключа",
        )


@router.get("/status", response_model=SyncStatusOut)
async def sync_status(session: SessionDep, _: CurrentUser) -> SyncStatusOut:
    return SyncStatusOut(**await sync_service.status(session))


@router.post("/push")
async def push(session: SessionDep, _: CurrentUser) -> dict:
    """Выгрузить накопленные изменения немедленно, не дожидаясь планировщика."""
    _require_sheets()
    try:
        result = await sync_service.push_pending(session, SheetsClient.from_settings())
    except SheetsUnavailable as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {"updated": result.updated, "appended": result.appended}


@router.post("/pull")
async def pull(session: SessionDep, _: CurrentUser) -> dict:
    """Забрать правки, сделанные руками в таблице."""
    _require_sheets()
    try:
        result = await sync_service.pull_edits(session, SheetsClient.from_settings())
    except SheetsUnavailable as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {"applied": result.applied, "created": result.created, "skipped": result.skipped}


@router.post("/resync")
async def resync(_: CurrentUser) -> dict:
    """Полная перезаливка журнала в таблицу."""
    _require_sheets()
    try:
        return await resync_now()
    except SheetsUnavailable as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
