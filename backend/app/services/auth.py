"""Вход в Mini App: initData -> сессионный токен."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User
from app.repositories import users as users_repo
from app.security.initdata import InitDataError, TelegramUser, validate_init_data
from app.security.tokens import issue_token
from app.services import bootstrap

log = logging.getLogger(__name__)


class AccessDenied(PermissionError):
    """Пользователь не в белом списке. Отдаётся как 403."""


async def register_user(session: AsyncSession, tg_user: TelegramUser) -> User:
    """Заводит пользователя и всё, без чего он не сможет работать (личный счёт, справочники)."""
    if not settings.is_allowed(tg_user.id):
        log.warning("отказано в доступе telegram_id=%s", tg_user.id)
        raise AccessDenied("доступ к приложению не разрешён")

    await bootstrap.ensure_reference_data(session)
    user = await users_repo.upsert_from_telegram(session, tg_user)
    await bootstrap.ensure_personal_account(session, user)
    return user


async def login(session: AsyncSession, init_data: str) -> tuple[User, str, int]:
    try:
        tg_user = validate_init_data(
            init_data, settings.bot_token, settings.init_data_max_age_seconds
        )
    except InitDataError as exc:
        # Причину пишем в лог, наружу отдаём только 401: подсказывать атакующему, что
        # именно не сошлось, незачем, а при настройке сервера эта строка экономит час
        log.warning("вход отклонён: %s", exc)
        raise

    user = await register_user(session, tg_user)
    token, expires_at = issue_token(user.id, user.telegram_id)
    return user, token, expires_at


async def dev_login(session: AsyncSession) -> tuple[User, str, int]:
    """Локальная разработка и демо без Telegram. Включается только DEV_AUTH_BYPASS=true."""
    if not settings.dev_auth_bypass:
        raise AccessDenied("dev-вход выключен")

    telegram_id = settings.dev_telegram_id or 1
    await bootstrap.ensure_reference_data(session)

    # Существующего человека не переименовываем: в демо DEV_TELEGRAM_ID указывает
    # на заранее заведённую Аню, и войти под ней надо как под Аней, а не как под «Dev»
    user = await users_repo.get_by_telegram_id(session, telegram_id)
    if user is None:
        user = await users_repo.upsert_from_telegram(
            session, TelegramUser(id=telegram_id, first_name="Dev")
        )

    await bootstrap.ensure_personal_account(session, user)
    token, expires_at = issue_token(user.id, user.telegram_id)
    return user, token, expires_at
