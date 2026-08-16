"""Настройка ежедневного напоминания — своего и только своего.

Чужие настройки через API не видны и не правятся: id пользователя в адресе нет,
берётся тот, чей токен предъявлен.
"""

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.api.schemas import ReminderOut, ReminderUpdate
from app.config import settings
from app.models import User
from app.services import reminders as reminders_service

router = APIRouter(tags=["reminders"])


def _view(user: User) -> ReminderOut:
    return ReminderOut(
        enabled=user.reminder_enabled,
        time=user.reminder_time or reminders_service.DEFAULT_TIME,
        tz=user.reminder_tz or settings.default_timezone,
        delivery_ready=bool(settings.bot_token) and settings.bot_mode != "off",
    )


@router.get("/me/reminder", response_model=ReminderOut)
async def get_reminder(user: CurrentUser) -> ReminderOut:
    return _view(user)


@router.put("/me/reminder", response_model=ReminderOut)
async def set_reminder(
    payload: ReminderUpdate, session: SessionDep, user: CurrentUser
) -> ReminderOut:
    try:
        updated = await reminders_service.update_settings(
            session,
            user,
            enabled=payload.enabled,
            at=payload.time,
            tz=payload.tz,
        )
    except reminders_service.ReminderError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return _view(updated)
