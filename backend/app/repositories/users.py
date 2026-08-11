from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.security.initdata import TelegramUser


async def get_by_id(session: AsyncSession, user_id: str) -> User | None:
    return await session.get(User, user_id)


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


async def list_all(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.created_at))
    return list(result.scalars())


async def upsert_from_telegram(session: AsyncSession, tg_user: TelegramUser) -> User:
    """Первый вход создаёт пользователя, последующие — обновляют имя.

    Проверку allowed_telegram_ids делает вызывающий код: репозиторий про политику доступа
    ничего не знает.
    """
    user = await get_by_telegram_id(session, tg_user.id)
    if user is None:
        user = User(
            telegram_id=tg_user.id,
            display_name=tg_user.display_name,
            username=tg_user.username,
        )
        session.add(user)
        await session.flush()
        return user

    if user.display_name != tg_user.display_name or user.username != tg_user.username:
        user.display_name = tg_user.display_name
        user.username = tg_user.username
    return user
