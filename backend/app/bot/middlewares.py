import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser

from app.config import settings
from app.db import get_session_factory
from app.security.initdata import TelegramUser
from app.services import auth as auth_service

log = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    """Пускаем в бота только пользователей из белого списка.

    Приложение приватное, поэтому чужие апдейты просто игнорируем: отвечать на них —
    значит подтверждать, что бот существует и что-то умеет.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        if tg_user is None or not settings.is_allowed(tg_user.id):
            if tg_user is not None:
                log.warning("бот: отклонён telegram_id=%s", tg_user.id)
            return None
        return await handler(event, data)


class DatabaseMiddleware(BaseMiddleware):
    """Открывает сессию на апдейт и кладёт в data сессию и доменного пользователя."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser = data["event_from_user"]
        async with get_session_factory()() as session:
            try:
                user = await auth_service.register_user(
                    session,
                    TelegramUser(
                        id=tg_user.id,
                        first_name=tg_user.first_name or "",
                        last_name=tg_user.last_name or "",
                        username=tg_user.username,
                    ),
                )
                data["session"] = session
                data["user"] = user
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
