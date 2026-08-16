"""Общий планировщик фоновых заданий.

APScheduler внутри того же процесса: для двух пользователей отдельный воркер, брокер
и Celery — это три лишних контейнера ради пары периодических функций.

Заданий сейчас два вида: выгрузка в Google Sheets и ежедневные напоминания. Каждое
включается само по себе, и если не включилось ни одно, планировщик не поднимается вовсе.
"""

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot import notify
from app.config import settings
from app.sync import scheduler as sync_jobs

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _run_reminders(bot: Bot) -> None:
    try:
        await notify.send_due_reminders(bot)
    except Exception:  # noqa: BLE001 — упавшее задание не должно уносить планировщик
        log.exception("ошибка рассылки напоминаний")


def start_scheduler(bot: Bot | None = None) -> AsyncIOScheduler | None:
    global _scheduler
    scheduler = AsyncIOScheduler(timezone="UTC")
    jobs = sync_jobs.register_jobs(scheduler)

    if bot is not None and settings.reminders_enabled:
        # Раз в минуту, а не «в 21:00»: время у каждого своё, поясов много, и проверка
        # для пары человек стоит одного COUNT по индексу. Заодно это чинит пропуски:
        # если контейнер перезапускали в 21:00, напоминание уйдёт в 21:01
        scheduler.add_job(
            _run_reminders,
            "cron",
            minute="*",
            args=[bot],
            id="daily_reminders",
            max_instances=1,
            coalesce=True,
        )
        log.info("напоминания включены, проверка раз в минуту")
        jobs = True
    elif bot is None:
        log.info("напоминания выключены: бот не запущен")

    if not jobs:
        return None

    scheduler.start()
    _scheduler = scheduler
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
