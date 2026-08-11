import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import settings
from app.db import get_engine

# Импорт моделей обязателен: без него metadata пустая и autogenerate снесёт все таблицы
from app.models import Base  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure(connection) -> None:  # noqa: ANN001
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite не умеет ALTER COLUMN: batch-режим пересоздаёт таблицу под капотом
        render_as_batch=True,
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine: AsyncEngine = get_engine()
    async with engine.connect() as connection:
        await connection.run_sync(lambda sync_conn: _configure(sync_conn))
        await connection.run_sync(lambda _: context.run_migrations())
        await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
