from datetime import date

from sqlalchemy import BigInteger, Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, ULIDMixin


class User(ULIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64))
    username: Mapped[str | None] = mapped_column(String(64), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- ежедневное напоминание внести траты ---
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # «21:00» по местному времени пользователя. Строкой, а не Time: ровно в этом виде
    # значение приходит из <input type="time"> и в этом же уходит обратно на клиент
    reminder_time: Mapped[str] = mapped_column(String(5), default="21:00")
    # Имя зоны IANA («Europe/Moscow»). Пустая строка — брать DEFAULT_TIMEZONE из настроек.
    # Не смещение в минутах: смещение сломается при переходе на летнее время
    reminder_tz: Mapped[str] = mapped_column(String(64), default="")
    # Местная дата последнего отправленного напоминания — защита от повторов
    reminder_last_sent_on: Mapped[date | None] = mapped_column(Date, default=None)

    def __repr__(self) -> str:
        return f"<User {self.display_name} tg={self.telegram_id}>"
