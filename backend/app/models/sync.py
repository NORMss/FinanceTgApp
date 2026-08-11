from datetime import datetime

from sqlalchemy import Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import OutboxOp
from app.util.dates import now


class SyncOutbox(Base):
    """Очередь изменений на выгрузку в Google Sheets.

    Смысл паттерна: запись в БД и отправка в Google — разные по надёжности операции.
    Транзакция коммитит факт «изменилось» вместе с самими данными, а доставка идёт
    отдельно и переживает недоступность API, 429 и перезапуск контейнера.
    """

    __tablename__ = "sync_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(26), index=True)
    op: Mapped[OutboxOp] = mapped_column(Enum(OutboxOp, native_enum=False, length=16))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=now)
    processed_at: Mapped[datetime | None] = mapped_column(default=None, index=True)

    def __repr__(self) -> str:
        return f"<Outbox {self.entity}:{self.entity_id} {self.op}>"


class AppSetting(TimestampMixin, Base):
    """Мелкое key-value состояние приложения: отметки последнего синка, версия схемы листа и т.п."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
