from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, String, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.util.dates import now
from app.util.ids import new_ulid

# Явные имена ограничений обязательны: без них Alembic не сможет пересоздавать таблицы
# в SQLite (batch mode), и любая миграция с изменением колонки упрётся в безымянный constraint.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class TZDateTime(TypeDecorator):
    """datetime, который остаётся aware после round-trip через SQLite.

    SQLite не хранит таймзону, поэтому нормализуем к UTC при записи и проставляем UTC при чтении.
    """

    impl = DateTime
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        # На Postgres это станет TIMESTAMP WITH TIME ZONE, на SQLite флаг ни на что не влияет
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {datetime: TZDateTime}


class ULIDMixin:
    """Первичный ключ — ULID: сортируется по времени и переживает выгрузку в Google Sheets."""

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_ulid)


class TimestampMixin:
    """created_at/updated_at нужны не для красоты, а для синхронизации: по updated_at
    воркер понимает, что строку надо переотправить в таблицу."""

    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)
