"""Исходящие сообщения бота, которые никто не запрашивал.

Пока такое одно — ежедневное напоминание внести траты. Кому его слать, решает
app.services.reminders; здесь только доставка и обработка отказов Telegram.
"""

import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from app.bot.keyboards import open_app_button
from app.db import get_session_factory
from app.services import reminders

log = logging.getLogger(__name__)

TEXT = (
    "🧾 <b>Траты за сегодня</b>\n"
    "Кажется, сегодняшний день ещё не записан. Кинь сумму строкой — "
    "<code>500 продукты</code> — или открой приложение."
)


async def send_due_reminders(bot: Bot, moment: datetime | None = None) -> int:
    """Рассылает напоминания тем, кому пора. Возвращает число отправленных."""
    async with get_session_factory()() as session:
        try:
            due = await reminders.pending(session, moment)
        except Exception:  # noqa: BLE001 — задание не должно убивать планировщик
            log.exception("не удалось составить список напоминаний")
            return 0

        sent = 0
        for item in due:
            try:
                await bot.send_message(
                    item.user.telegram_id, TEXT, reply_markup=open_app_button()
                )
            except TelegramForbiddenError:
                # Бот заблокирован или чат удалён. Отмечаем как отправленное: повторять
                # каждую минуту до полуночи бессмысленно, ответ не изменится
                log.info("напоминание не доставлено, бот заблокирован: %s", item.user.id)
                reminders.mark_sent(item)
            except Exception:  # noqa: BLE001 — сеть, 429, недоступный Telegram
                # Отметку не ставим: следующий тик попробует ещё раз, и так до местной полуночи
                log.warning("напоминание не ушло, попробую позже: %s", item.user.id)
            else:
                reminders.mark_sent(item)
                sent += 1

        await session.commit()

    if sent:
        log.info("отправлено напоминаний: %s", sent)
    return sent
