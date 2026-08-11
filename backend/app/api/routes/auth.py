from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.api.schemas import LoginRequest, LoginResponse, UserOut
from app.config import settings
from app.security.initdata import InitDataError
from app.services import auth as auth_service

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, session: SessionDep) -> LoginResponse:
    """Обменивает initData из Telegram на сессионный токен."""
    try:
        if payload.init_data:
            user, token, expires_at = await auth_service.login(session, payload.init_data)
        else:
            # Пустая initData допустима только в dev-режиме — иначе это попытка зайти мимо Telegram
            user, token, expires_at = await auth_service.dev_login(session)
    except InitDataError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "initData не прошла проверку") from exc
    except auth_service.AccessDenied as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

    return LoginResponse(
        token=token,
        expires_at=expires_at,
        user=UserOut.model_validate(user),
        base_currency=settings.base_currency,
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
