from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, ULIDMixin
from app.models.enums import TransactionType, TxSource


class Transaction(ULIDMixin, TimestampMixin, Base):
    """Одна финансовая операция.

    Соглашения:
      * amount_minor всегда положительный, направление задаёт `type`;
      * для transfer заполнены оба счёта: account_id — откуда, counter_account_id — куда;
      * удаление мягкое (deleted_at), иначе синхронизация с таблицей не сможет
        отличить «строку удалили» от «строку ещё не выгрузили».
    """

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        Index("ix_transactions_occurred_at", "occurred_at"),
        Index("ix_transactions_period", "deleted_at", "occurred_at"),
    )

    occurred_at: Mapped[datetime] = mapped_column()
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, native_enum=False, length=16), index=True
    )
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="RUB")

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    counter_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), default=None
    )
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), default=None, index=True
    )
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)

    note: Mapped[str] = mapped_column(Text, default="")
    # Плоский список меток через запятую: JSON здесь избыточен, а фильтровать LIKE проще
    tags: Mapped[str] = mapped_column(String(255), default="")

    source: Mapped[TxSource] = mapped_column(
        Enum(TxSource, native_enum=False, length=16), default=TxSource.APP
    )
    # Ключ идемпотентности для импорта выписок и повторной заливки из таблицы
    external_id: Mapped[str | None] = mapped_column(String(128), default=None, unique=True)

    deleted_at: Mapped[datetime | None] = mapped_column(default=None, index=True)

    splits: Mapped[list["TxSplit"]] = relationship(
        back_populates="transaction", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def signed_minor(self) -> int:
        """Влияние на счёт account_id: расход и перевод уменьшают, доход увеличивает."""
        return self.amount_minor if self.type == TransactionType.INCOME else -self.amount_minor

    def __repr__(self) -> str:
        return f"<Transaction {self.type} {self.amount_minor} {self.occurred_at:%Y-%m-%d}>"


class TxSplit(ULIDMixin, Base):
    """Как операция делится между участниками — основа расчёта «кто кому должен».

    Сумма долей равна amount_minor. Для личных трат сплит просто не создаётся.
    """

    __tablename__ = "tx_splits"
    __table_args__ = (Index("ix_tx_splits_user", "user_id"),)

    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    share_minor: Mapped[int] = mapped_column(Integer)

    transaction: Mapped[Transaction] = relationship(back_populates="splits")
