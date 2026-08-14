import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import api_router
from app.bot.setup import create_bot, create_dispatcher, setup_webhook, start_polling
from app.config import settings
from app.db import dispose_engine, get_session_factory
from app.logging_setup import configure_logging
from app.services import bootstrap
from app.sync.scheduler import start_scheduler, stop_scheduler

log = logging.getLogger(__name__)

# Локальная разработка: Vite поднимается на 5173, API — на 8000, это разные origin
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("старт FinanceTgApp %s, режим бота: %s", __version__, settings.bot_mode)
    # Статика монтируется на импорте (важен порядок роутов), а сообщить об этом можно
    # только здесь: до configure_logging у логгера ещё нет обработчиков
    if STATIC_DIR.is_dir():
        log.info("статика Mini App отдаётся приложением из %s", STATIC_DIR)

    async with get_session_factory()() as session:
        await bootstrap.ensure_reference_data(session)
        await session.commit()

    polling_task: asyncio.Task | None = None
    if settings.bot_mode != "off" and settings.bot_token:
        app.state.bot = create_bot()
        app.state.dispatcher = create_dispatcher()
        # Печатаем, чьим токеном представилось приложение. Подпись initData считается
        # именно этим токеном, поэтому при 401 первым делом сверяют username здесь
        # с ботом, из меню которого открыли Mini App.
        try:
            me = await app.state.bot.get_me()
            log.info("токен принадлежит боту @%s (id=%s)", me.username, me.id)
        except Exception as exc:  # noqa: BLE001 — Telegram может быть недоступен на старте
            log.warning("не удалось получить данные бота: %s", exc)
        if settings.bot_mode == "polling":
            polling_task = await start_polling(app.state.bot, app.state.dispatcher)
        else:
            await setup_webhook(app.state.bot)
    else:
        app.state.bot = None
        app.state.dispatcher = None
        log.warning("бот выключен: не задан BOT_TOKEN или BOT_MODE=off")

    start_scheduler()

    try:
        yield
    finally:
        stop_scheduler()
        if polling_task is not None:
            polling_task.cancel()
            await asyncio.gather(polling_task, return_exceptions=True)
        if app.state.bot is not None:
            await app.state.bot.session.close()
        await dispose_engine()
        log.info("остановлено")


app = FastAPI(
    title="FinanceTgApp",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.public_url, *DEV_ORIGINS],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.post(settings.webhook_path, include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Приём апдейтов от Telegram.

    Секретный заголовок обязателен: без него любой, кто узнает адрес, сможет
    присылать боту поддельные апдейты.
    """
    if settings.webhook_secret and x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "неверный секрет вебхука")

    dispatcher = getattr(request.app.state, "dispatcher", None)
    bot = getattr(request.app.state, "bot", None)
    if dispatcher is None or bot is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "бот не запущен")

    update = Update.model_validate(await request.json(), context={"bot": bot})
    await dispatcher.feed_update(bot, update)
    return {"ok": True}


# Отдача собранного фронта самим приложением. По умолчанию этим занимается Caddy из
# docker-compose, но если сервер уже занят чужим веб-сервером, статику проще раздавать
# отсюда: тогда наружу торчит один порт, и внешнему прокси достаточно одного location.
STATIC_DIR = settings.static_dir or Path(__file__).resolve().parents[2] / "frontend" / "dist"
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")
