from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, ULIDMixin
from app.models.enums import AccountKind


class Account(ULIDMixin, TimestampMixin, Base):
    """Кошелёк/карта/копилка.

    is_shared отличает общий счёт от личного: операции по общему счёту участвуют
    в расчёте «кто кому должен», личные — нет.
    """

    __tablename__ = "accounts"

    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[AccountKind] = mapped_column(
        Enum(AccountKind, native_enum=False, length=16), default=AccountKind.CARD
    )
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    owner_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None, index=True
    )
    # Стартовый остаток на момент заведения счёта в приложении
    opening_balance_minor: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sort: Mapped[int] = mapped_column(Integer, default=100)

    def __repr__(self) -> str:
        return f"<Account {self.name}>"
