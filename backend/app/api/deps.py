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


async def get_current_user(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Достаёт пользователя из сессионного JWT (`Authorization: Bearer <token>`).

    Дополнительно перепроверяем белый список: если человека убрали из ALLOWED_TELEGRAM_IDS,
    его выданный ранее токен должен перестать работать сразу, а не через неделю.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нет токена")

    try:
        claims = decode_token(authorization.split(" ", 1)[1].strip())
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "токен невалиден") from exc

    if not settings.dev_auth_bypass and not settings.is_allowed(claims.telegram_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "доступ отозван")

    user = await users_repo.get_by_id(session, claims.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "пользователь не найден")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
