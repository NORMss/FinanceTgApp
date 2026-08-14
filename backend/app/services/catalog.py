"""Правила работы с деревом категорий.

Дерево ровно двухуровневое: «Супермаркет» -> «Пятёрочка», «КБ». Ограничение не
техническое, а продуктовое — на третьем уровне отчёт перестаёт читаться, а список
категорий в форме ввода не помещается на экран. Здесь же живут проверки, без которых
дерево быстро превращается в мусор: одинаковые имена у соседей, подкатегория дохода
под категорией расхода, попытка сделать категорию потомком самой себя.
"""

import unicodedata

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, CategoryKind
from app.repositories import categories as categories_repo

MAX_NAME = 64
MAX_ICON = 16
ZWJ = "\u200d"  # U+200D, невидим в редакторе — поэтому кодом, а не символом


class CatalogError(ValueError):
    """Нарушено правило справочника. Наружу отдаётся как 400."""


def clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise CatalogError("название не может быть пустым")
    if len(name) > MAX_NAME:
        raise CatalogError(f"название длиннее {MAX_NAME} символов")
    return name


def clean_icon(raw: str) -> str:
    """Значок категории: эмодзи или пара букв.

    Эмодзи не требуем — «КБ» перед названием работает не хуже. Режем только то, что
    ломает вёрстку: переводы строк и невидимые управляющие символы. Эмодзи из нескольких
    кодовых точек (ZWJ-последовательности) при этом остаются целыми.
    """
    icon = "".join(ch for ch in raw.strip() if _icon_char_allowed(ch))
    if len(icon) > MAX_ICON:
        raise CatalogError("значок слишком длинный — хватит одного эмодзи или пары букв")
    return icon


def _icon_char_allowed(ch: str) -> bool:
    if ch == ZWJ:
        return True  # склейка составных эмодзи: 👨‍👩‍👧 без неё рассыпется на три
    return unicodedata.category(ch) not in {"Cc", "Cf", "Zl", "Zp"}


async def _ensure_unique(
    session: AsyncSession,
    *,
    name: str,
    kind: CategoryKind,
    parent_id: str | None,
    exclude_id: str | None = None,
) -> None:
    siblings = (
        await categories_repo.list_children(session, parent_id)
        if parent_id
        else [
            category
            for category in await categories_repo.list_all(
                session, kind=kind, include_archived=True
            )
            if category.parent_id is None
        ]
    )
    for sibling in siblings:
        if sibling.id == exclude_id or sibling.archived:
            continue
        if sibling.name.casefold() == name.casefold():
            where = "в этой категории" if parent_id else "среди категорий"
            raise CatalogError(f"«{name}» уже есть {where}")


async def _resolve_parent(
    session: AsyncSession, parent_id: str | None, *, kind: CategoryKind
) -> Category | None:
    if not parent_id:
        return None
    parent = await categories_repo.get(session, parent_id)
    if parent is None:
        raise CatalogError("родительская категория не найдена")
    if parent.parent_id is not None:
        raise CatalogError("глубже двух уровней вкладывать нельзя")
    if parent.kind != kind:
        raise CatalogError("подкатегория должна быть того же типа, что и родитель")
    return parent


async def create_category(
    session: AsyncSession,
    *,
    name: str,
    kind: CategoryKind = CategoryKind.EXPENSE,
    icon: str = "",
    parent_id: str | None = None,
    sort: int = 100,
) -> Category:
    name = clean_name(name)
    icon = clean_icon(icon)
    parent = await _resolve_parent(session, parent_id, kind=kind)
    if parent is not None:
        kind = parent.kind
    await _ensure_unique(session, name=name, kind=kind, parent_id=parent_id)
    return await categories_repo.create(
        session, name=name, kind=kind, icon=icon, parent_id=parent_id, sort=sort
    )


async def update_category(
    session: AsyncSession,
    category: Category,
    *,
    name: str | None = None,
    icon: str | None = None,
    parent_id: str | None = None,
    move_to_root: bool = False,
    sort: int | None = None,
    archived: bool | None = None,
) -> Category:
    children = await categories_repo.list_children(session, category.id)

    if move_to_root:
        category.parent_id = None
    elif parent_id is not None:
        if parent_id == category.id:
            raise CatalogError("категория не может быть вложена в саму себя")
        if children:
            raise CatalogError(
                "у категории есть подкатегории — сначала перенесите или удалите их"
            )
        parent = await _resolve_parent(session, parent_id, kind=category.kind)
        assert parent is not None
        category.parent_id = parent.id

    if name is not None:
        category.name = clean_name(name)
    if icon is not None:
        category.icon = clean_icon(icon)
    if sort is not None:
        category.sort = sort
    if archived is not None:
        category.archived = archived
        # Спрятанная категория не должна оставлять на виду своих детей: они окажутся
        # в списке без родителя, и выбрать их можно будет только случайно
        for child in children:
            child.archived = archived

    await _ensure_unique(
        session,
        name=category.name,
        kind=category.kind,
        parent_id=category.parent_id,
        exclude_id=category.id,
    )
    await session.flush()
    return category


async def delete_category(session: AsyncSession, category: Category) -> str:
    """Удаляет категорию, если она никому не нужна, иначе прячет.

    Возвращает «deleted» или «archived» — вызывающему нужно сказать пользователю,
    что именно произошло. Удалять категорию с операциями нельзя: журнал за прошлые
    месяцы потерял бы разбивку, а восстановить её потом неоткуда.
    """
    children = await categories_repo.list_children(session, category.id)
    used = await categories_repo.usage_count(session, category.id)

    if used or children:
        category.archived = True
        for child in children:
            child.archived = True
        await session.flush()
        return "archived"

    await categories_repo.remove(session, category)
    return "deleted"


async def expand_ids(session: AsyncSession, category_ids: list[str]) -> list[str]:
    """Добавляет к выбранным категориям их подкатегории.

    Пользователь, выбравший «Продукты», ждёт увидеть и «Пятёрочку»: отдельно выбирать
    каждого ребёнка ради фильтра — работа, которую должен делать сервер.
    """
    if not category_ids:
        return []
    expanded = list(dict.fromkeys(category_ids))
    known = set(expanded)
    for category_id in category_ids:
        for child in await categories_repo.list_children(session, category_id):
            if child.id not in known:
                known.add(child.id)
                expanded.append(child.id)
    return expanded


def full_name(category: Category, parents: dict[str, Category]) -> str:
    """«Супермаркет · Пятёрочка» — для отчётов, выгрузки и таблицы."""
    parent = parents.get(category.parent_id or "")
    return f"{parent.name} · {category.name}" if parent else category.name
