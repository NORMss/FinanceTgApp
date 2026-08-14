import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
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
    # Схема API — это карта всех ручек. Приватному приложению на двоих она не нужна,
    # а нашедшему адрес экономит всю разведку. Открывается через ENABLE_DOCS=true.
    docs_url="/api/docs" if settings.enable_docs else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.enable_docs else None,
)

# Origin'ы Vite нужны только при локальной разработке. В продакшене их быть не должно:
# лишний разрешённый origin — это лишний способ дёргать API из чужой вкладки
ALLOWED_ORIGINS = [settings.public_url]
if settings.dev_auth_bypass:
    ALLOWED_ORIGINS += DEV_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Заголовки, которые запрещают лишнее и убирают приметы сервера.

    Mini App открывается внутри Telegram, поэтому frame-ancestors разрешает только его
    домены: в чужой iframe страницу не вставить, кликджекинг отпадает. Заголовок `Server`
    с версией uvicorn снимается не здесь, а флагом `--no-server-header`: его дописывает
    сам сервер уже после ASGI-приложения, и из middleware до него не дотянуться.
    """
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


SECURITY_HEADERS = {
    "Content-Security-Policy": "; ".join(
        (
            "default-src 'self'",
            # Telegram отдаёт telegram-web-app.js со своего домена и подставляет
            # инлайновые стили в разметку, поэтому unsafe-inline только для стилей
            "script-src 'self' https://telegram.org",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data:",
            "connect-src 'self'",
            "frame-ancestors https://web.telegram.org https://telegram.org",
            "base-uri 'none'",
            "form-action 'none'",
            "object-src 'none'",
        )
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    # Приложение приватное: в поиске ему делать нечего
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """Ни трассировки, ни текста исключения наружу — только в лог."""
    log.exception("необработанная ошибка на %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Внутренняя ошибка"}, status_code=500)


@app.get("/robots.txt", include_in_schema=False)
async def robots() -> PlainTextResponse:
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


app.include_router(api_router)


@app.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    include_in_schema=False,
)
async def unknown_api(path: str) -> JSONResponse:
    """Заглушка для несуществующих ручек API.

    Без неё запрос к /api/чего-нибудь проваливался бы в раздачу статики и отвечал
    по-разному в зависимости от того, есть ли такой файл. Одинаковый ответ на всё
    неизвестное не даёт перебором нащупать, что в API есть, а чего нет.
    """
    return JSONResponse({"detail": "Не найдено"}, status_code=404)


@app.post(settings.webhook_path, include_in_schema=False)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Приём апдейтов от Telegram.

    Секретный заголовок обязателен: без него любой, кто узнает адрес, сможет
    присылать боту поддельные апдейты.
    """
    if settings.webhook_secret and not hmac.compare_digest(
        x_telegram_bot_api_secret_token or "", settings.webhook_secret
    ):
        # Сравнение постоянного времени: обычное «!=» выходит на первом несовпавшем
        # байте и по времени ответа выдаёт, насколько угадан префикс секрета
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")

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
