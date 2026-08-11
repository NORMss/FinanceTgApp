from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, ULIDMixin
from app.models.enums import CategoryKind


class Category(ULIDMixin, TimestampMixin, Base):
    """Категория трат или доходов.

    parent_id заложен под подкатегории: в UI первой версии дерево не показываем,
    но добавить его потом можно без миграции данных.
    """

    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[CategoryKind] = mapped_column(
        Enum(CategoryKind, native_enum=False, length=16), default=CategoryKind.EXPENSE, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), default=None
    )
    icon: Mapped[str] = mapped_column(String(8), default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sort: Mapped[int] = mapped_column(Integer, default=100)

    def __repr__(self) -> str:
        return f"<Category {self.name}>"


class CategoryRule(ULIDMixin, TimestampMixin, Base):
    """Правило автокатегоризации: подстрока в тексте -> категория.

    Закрывает большую часть быстрого ввода из чата без всякого ИИ.
    """

    __tablename__ = "category_rules"

    pattern: Mapped[str] = mapped_column(String(128))
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    # Сколько раз правило сработало — по этому полю потом чистим мусорные правила
    hits: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return f"<CategoryRule {self.pattern!r}>"
