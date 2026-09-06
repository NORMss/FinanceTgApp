"""Сборка бота и режимы получения апдейтов.

polling — для локальной разработки: не нужен ни публичный домен, ни туннель.
webhook — для прода: Telegram сам стучится в наш FastAPI, приложение не держит
постоянный исходящий запрос и спокойно переживает рестарты.

Регистрация в Telegram (`bring_up`) вынесена в фоновую задачу и переживает недоступность
api.telegram.org: раньше она делалась на старте приложения, а uvicorn открывает порт
только после того, как стартовый код закончится. Каждая секунда ожидания Telegram была
секундой, в которую прокси отвечал 502 на любой запрос Mini App, а исключение оттуда
роняло процесс целиком — и рестарт начинал то же ожидание заново.
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

# Свой срок на каждый вызов Telegram. По умолчанию aiogram ждёт ответа минуту,
# и на старте это минута на вызов при недоступном api.telegram.org.
CONNECT_TIMEOUT = 10
# С чего начинаем повторять регистрацию и докуда наращиваем паузу
RETRY_START = 5
RETRY_MAX = 300

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


async def _register(bot: Bot) -> None:
    """Сообщает Telegram, куда слать апдейты и какие команды показывать в меню."""
    if settings.bot_mode == "polling":
        # Вебхук и polling взаимно исключают друг друга: пока висит вебхук,
        # getUpdates отвечает отказом
        await bot.delete_webhook(drop_pending_updates=False, request_timeout=CONNECT_TIMEOUT)
    else:
        await bot.set_webhook(
            url=settings.webhook_url,
            secret_token=settings.webhook_secret or None,
            drop_pending_updates=False,
            allowed_updates=["message", "callback_query"],
            request_timeout=CONNECT_TIMEOUT,
        )
        log.info("вебхук установлен: %s", settings.webhook_url)
    await bot.set_my_commands(COMMANDS, request_timeout=CONNECT_TIMEOUT)


async def bring_up(bot: Bot, dispatcher: Dispatcher) -> None:
    """Регистрация в Telegram и приём апдейтов. Запускается фоновой задачей.

    Недоступный Telegram здесь — не повод падать. Mini App и API от бота не зависят:
    человек открывает приложение и продолжает вносить траты, а регистрация повторяется
    с растущей паузой, пока не пройдёт. Раньше исключение отсюда прерывало старт
    приложения, контейнер уходил в перезапуск, и вместе с ботом на всё это время
    пропадал API — то есть в Mini App на каждом экране был 502.
    """
    delay = RETRY_START
    while True:
        try:
            # Печатаем, чьим токеном представилось приложение. Подпись initData считается
            # именно этим токеном, поэтому при 401 первым делом сверяют username здесь
            # с ботом, из меню которого открыли Mini App.
            me = await bot.get_me(request_timeout=CONNECT_TIMEOUT)
            log.info("токен принадлежит боту @%s (id=%s)", me.username, me.id)
            await _register(bot)
            break
        # CancelledError наследуется от BaseException и сюда не попадает: остановка
        # приложения отменяет задачу, а не начинает очередной круг ожидания
        except Exception as exc:  # noqa: BLE001 — сеть, 429, блокировка Telegram
            log.warning("Telegram не отвечает (%s), повтор через %sс", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX)

    if settings.bot_mode == "polling":
        log.info("бот запущен в режиме polling")
        await dispatcher.start_polling(bot, handle_signals=False)
    else:
        log.info("бот готов принимать апдейты вебхуком")
