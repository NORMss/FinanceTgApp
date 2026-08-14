import logging
from collections.abc import AsyncIterator
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import session_scope
from app.models import User
from app.repositories import users as users_repo
from app.security.tokens import decode_token


async def get_session() -> AsyncIterator[AsyncSession]:
    async for session in session_scope():
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


log = logging.getLogger(__name__)

# Единый ответ на любую проблему с токеном. Различать «токен просрочен», «подпись
# не та» и «тебя убрали из списка» полезно только тому, кто подбирает доступ:
# приложение в любом из случаев делает одно и то же — переспрашивает вход у Telegram.
NO_ACCESS = "Нет доступа"


def _denied(reason: str) -> HTTPException:
    log.info("запрос отклонён: %s", reason)
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        f"{NO_ACCESS}: {reason}" if settings.debug_errors else NO_ACCESS,
    )


async def get_current_user(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Достаёт пользователя из сессионного JWT (`Authorization: Bearer <token>`).

    Дополнительно перепроверяем белый список: если человека убрали из ALLOWED_TELEGRAM_IDS,
    его выданный ранее токен должен перестать работать сразу, а не через неделю.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _denied("нет токена")

    try:
        claims = decode_token(authorization.split(" ", 1)[1].strip())
    except jwt.PyJWTError as exc:
        raise _denied("токен невалиден") from exc

    if not settings.dev_auth_bypass and not settings.is_allowed(claims.telegram_id):
        raise _denied(f"доступ отозван для telegram_id={claims.telegram_id}")

    user = await users_repo.get_by_id(session, claims.user_id)
    if user is None or not user.is_active:
        raise _denied("пользователь не найден или отключён")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
