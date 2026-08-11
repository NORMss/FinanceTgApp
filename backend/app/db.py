from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _ensure_sqlite_dir(url: str) -> None:
    marker = "sqlite+aiosqlite:///"
    if not url.startswith(marker):
        return
    path = Path(url[len(marker) :].split("?", 1)[0])
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _ensure_sqlite_dir(settings.database_url)
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            # SQLite не любит долгие блокировки: даём драйверу подождать вместо мгновенной ошибки
            connect_args={"timeout": 15} if settings.database_url.startswith("sqlite") else {},
        )
        if settings.database_url.startswith("sqlite"):
            _apply_sqlite_pragmas(_engine)
    return _engine


def _apply_sqlite_pragmas(engine: AsyncEngine) -> None:
    """WAL + foreign_keys. Без WAL один пишущий блокирует всех читающих."""

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection, _record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.close()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, autoflush=False
        )
    return _session_factory


async def session_scope() -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI: сессия на запрос, коммит на успехе, откат на исключении."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def healthcheck() -> bool:
    async with get_engine().connect() as connection:
        await connection.execute(text("SELECT 1"))
    return True


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
