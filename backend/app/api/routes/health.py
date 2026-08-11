from fastapi import APIRouter

from app import __version__
from app.config import settings
from app.db import healthcheck

router = APIRouter(tags=["service"])


@router.get("/health")
async def health() -> dict:
    """Проверка живости для docker healthcheck и мониторинга."""
    try:
        db_ok = await healthcheck()
    except Exception:  # noqa: BLE001 — наружу отдаём статус, а не трейс
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "version": __version__,
        "db": db_ok,
        "bot_mode": settings.bot_mode,
        "sheets": settings.sheets_ready,
    }
