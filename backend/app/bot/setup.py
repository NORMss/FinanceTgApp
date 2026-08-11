"""Сборка бота и режимы получения апдейтов.

polling — для локальной разработки: не нужен ни публичный домен, ни туннель.
webhook — для прода: Telegram сам стучится в наш FastAPI, приложение не держит
постоянный исходящий запрос и спокойно переживает рестарты.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.bot.handlers import router
from app.bot.middlewares import AccessMiddleware, DatabaseMiddleware
from app.config import settings

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand(command="month", description="Итоги за месяц"),
    BotCommand(command="balance", description="Остатки по счетам"),
    BotCommand(command="settle", description="Кто кому должен"),
    BotCommand(command="llm", description="Выгрузка для нейросети"),
    BotCommand(command="sync", description="Синхронизация с Google Sheets"),
    BotCommand(command="help", description="Как пользоваться"),
]


def create_bot() -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    # Порядок важен: сначала отсекаем чужих, только потом открываем сессию БД
    for observer in (dispatcher.message, dispatcher.callback_query):
        observer.middleware(AccessMiddleware())
        observer.middleware(DatabaseMiddleware())
    dispatcher.include_router(router)
    return dispatcher


async def start_polling(bot: Bot, dispatcher: Dispatcher) -> asyncio.Task:
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.set_my_commands(COMMANDS)
    log.info("бот запущен в режиме polling")
    return asyncio.create_task(dispatcher.start_polling(bot, handle_signals=False))


async def setup_webhook(bot: Bot) -> None:
    await bot.set_webhook(
        url=settings.webhook_url,
        secret_token=settings.webhook_secret or None,
        drop_pending_updates=False,
        allowed_updates=["message", "callback_query"],
    )
    await bot.set_my_commands(COMMANDS)
    log.info("вебхук установлен: %s", settings.webhook_url)
