import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser, SessionDep
from app.api.schemas import LoginRequest, LoginResponse, UserOut
from app.config import settings
from app.security.initdata import InitDataError
from app.security.ratelimit import RateLimiter, client_key
from app.services import auth as auth_service

log = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])

# Один и тот же ответ на любую причину отказа: подпись не сошлась, initData протухла,
# человека нет в белом списке. Снаружи это неразличимо, и перебирать нечего.
DENIED = "Не удалось войти"

_limiter = RateLimiter(settings.login_attempts, settings.login_window_seconds)


def _fail(request: Request, reason: str, code: int) -> HTTPException:
    """Логирует настоящую причину, наружу отдаёт обезличенный ответ.

    Подробности возвращаются, только если явно включён DEBUG_ERRORS — это режим
    первичной настройки сервера, а не рабочий.
    """
    key = client_key(request, trust_proxy=settings.trust_proxy_header)
    _limiter.register_failure(key)
    log.warning("вход отклонён (%s): %s", key, reason)
    detail = f"{DENIED}: {reason}" if settings.debug_errors else DENIED
    return HTTPException(code, detail)


@router.post("/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request, session: SessionDep) -> LoginResponse:
    """Обменивает initData из Telegram на сессионный токен."""
    key = client_key(request, trust_proxy=settings.trust_proxy_header)
    if _limiter.is_blocked(key):
        log.warning("вход заблокирован по частоте попыток: %s", key)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            DENIED,
            headers={"Retry-After": str(_limiter.retry_after(key))},
        )

    try:
        if payload.init_data:
            user, token, expires_at = await auth_service.login(session, payload.init_data)
        else:
            # Пустая initData допустима только в dev-режиме — иначе это попытка зайти мимо Telegram
            user, token, expires_at = await auth_service.dev_login(session)
    except InitDataError as exc:
        raise _fail(request, str(exc), status.HTTP_401_UNAUTHORIZED) from exc
    except auth_service.AccessDenied as exc:
        raise _fail(request, str(exc), status.HTTP_403_FORBIDDEN) from exc

    _limiter.reset(key)
    return LoginResponse(
        token=token,
        expires_at=expires_at,
        user=UserOut.model_validate(user),
        base_currency=settings.base_currency,
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
