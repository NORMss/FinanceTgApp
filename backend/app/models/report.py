"""Настройки отчёта, которые живут дольше одного открытия приложения.

Здесь две сущности, и разница между ними существенная. **Бюджет** — общий на семью:
лимит стоит на категории, а не на человеке, потому что «на продукты в месяц 25 000» —
это договорённость двоих, и держать её в двух экземплярах значит однажды обнаружить,
что экземпляры разошлись. **Сохранённый вид** — наоборот, личный: один считает
«сколько мы тратим без ипотеки», второму интереснее «только общий счёт», и навязывать
друг другу набор галочек незачем.
"""

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, ULIDMixin


class Budget(ULIDMixin, TimestampMixin, Base):
    """Месячный лимит по категории.

    Лимит именно месячный и единственный: недельные и годовые пришлось бы приводить
    друг к другу в каждом отчёте, а «сколько от лимита истрачено» имеет смысл ровно
    там, где период совпадает с периодом лимита. Отчёт за неделю или за год лимиты
    не показывает — цифра «17 % от месячного» за неделю не значит ничего.

    Лимит стоит на любой категории дерева, включая подкатегорию: «на кофе не больше
    3 000» — законное желание, а класть его на «Кафе» целиком неправильно.
    """

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("category_id", name="uq_budgets_category"),)

    category_id: Mapped[str] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True
    )
    limit_minor: Mapped[int] = mapped_column(Integer)


class ReportView(ULIDMixin, TimestampMixin, Base):
    """Именованный набор фильтров отчёта: «Быт», «Без ипотеки», «Только общее».

    Фильтры хранятся строкой JSON, а не колонками. Это осознанно: набор фильтров
    меняется вместе с экраном, и каждая новая галочка иначе стоила бы миграции.
    Ценность строки нулевая — потеряется, человек соберёт вид заново, — поэтому
    схема здесь не нужна, а гибкость нужна.
    """

    __tablename__ = "report_views"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_report_views_owner_name"),)

    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    sort: Mapped[int] = mapped_column(Integer, default=100)
