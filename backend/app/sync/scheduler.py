"""Фоновые задания синхронизации.

APScheduler внутри того же процесса: для двух пользователей отдельный воркер, брокер
и Celery — это три лишних контейнера ради одной периодической функции.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.db import get_session_factory
from app.repositories import outbox as outbox_repo
from app.sync.client import SheetsClient
from app.sync.service import full_resync, pull_edits, push_pending

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_push() -> None:
    async with get_session_factory()() as session:
        try:
            result = await push_pending(session, SheetsClient.from_settings())
            await session.commit()
            if result.updated or result.appended:
                log.info("Sheets: обновлено %s, добавлено %s", result.updated, result.appended)
        except Exception:  # noqa: BLE001 — задание не должно убивать планировщик
            await session.rollback()
            log.exception("ошибка выгрузки в Sheets")


async def _run_pull() -> None:
    async with get_session_factory()() as session:
        try:
            result = await pull_edits(session, SheetsClient.from_settings())
            await session.commit()
            if result.applied or result.created:
                log.info(
                    "Sheets: принято правок %s, новых строк %s", result.applied, result.created
                )
        except Exception:  # noqa: BLE001
            await session.rollback()
            log.exception("ошибка импорта из Sheets")


async def _run_cleanup() -> None:
    async with get_session_factory()() as session:
        try:
            removed = await outbox_repo.purge_processed(session)
            await session.commit()
            if removed:
                log.info("очередь синхронизации: удалено %s обработанных записей", removed)
        except Exception:  # noqa: BLE001
            await session.rollback()
            log.exception("ошибка очистки очереди")


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    if not settings.sheets_ready:
        log.info("синхронизация с Google Sheets выключена или не настроена")
        return None

    scheduler = AsyncIOScheduler(timezone="UTC")
    interval = max(15, settings.sheets_sync_interval)
    scheduler.add_job(_run_push, "interval", seconds=interval, id="sheets_push", max_instances=1)
    scheduler.add_job(
        _run_pull,
        "interval",
        seconds=max(300, interval * 5),
        id="sheets_pull",
        max_instances=1,
    )
    scheduler.add_job(_run_cleanup, "interval", hours=24, id="outbox_cleanup", max_instances=1)
    scheduler.start()
    _scheduler = scheduler
    log.info("планировщик синхронизации запущен, интервал %sс", interval)
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


async def resync_now() -> dict:
    """Ручная полная перезаливка — вызывается из API и из бота."""
    async with get_session_factory()() as session:
        result = await full_resync(session, SheetsClient.from_settings())
        await session.commit()
        return {"updated": result.updated, "appended": result.appended}
