"""Сессионный JWT.

Гонять HMAC-проверку initData на каждый запрос можно, но она привязана к auth_date и протухает
вместе с ним. Поэтому меняем initData на свой короткоживущий токен один раз при старте Mini App.
"""

from dataclasses import dataclass

import jwt

from app.config import settings
from app.util.dates import now

_ALGORITHM = "HS256"


@dataclass(frozen=True, slots=True)
class SessionClaims:
    user_id: str
    telegram_id: int


def issue_token(user_id: str, telegram_id: int) -> tuple[str, int]:
    expires_at = int(now().timestamp()) + settings.jwt_ttl_seconds
    payload = {
        "sub": user_id,
        "tg": telegram_id,
        "iat": int(now().timestamp()),
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM), expires_at


def decode_token(token: str) -> SessionClaims:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    return SessionClaims(user_id=str(payload["sub"]), telegram_id=int(payload["tg"]))
