"""Правила работы с деревом категорий.

Дерево ровно двухуровневое: «Супермаркет» -> «Пятёрочка», «КБ». Ограничение не
техническое, а продуктовое — на третьем уровне отчёт перестаёт читаться, а список
категорий в форме ввода не помещается на экран. Здесь же живут проверки, без которых
дерево быстро превращается в мусор: одинаковые имена у соседей, подкатегория дохода
под категорией расхода, попытка сделать категорию потомком самой себя.
"""

import unicodedata
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, CategoryKind
from app.repositories import categories as categories_repo
from app.repositories import outbox as outbox_repo

MAX_NAME = 64
MAX_ICON = 16
# Имя сущности в очереди синхронизации. Дублировать ledger.ENTITY здесь дешевле,
# чем тянуть весь модуль журнала ради одной строки и получить круговой импорт
TX_ENTITY = "transaction"
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


@dataclass(frozen=True, slots=True)
class Usage:
    """Что зацепит удаление категории. Показывается человеку до того, как он нажмёт «Удалить»."""

    transactions: int  # живых операций во всём поддереве
    children: int
    rules: int

    @property
    def needs_replacement(self) -> bool:
        return self.transactions > 0


class ReplacementRequired(CatalogError):
    """Категорию нельзя удалить молча: на ней висят операции, им нужна новая категория."""


async def subtree_ids(session: AsyncSession, category: Category) -> list[str]:
    """Сама категория и её подкатегории. Дерево двухуровневое, поэтому рекурсии нет."""
    children = await categories_repo.list_children(session, category.id)
    return [category.id, *(child.id for child in children)]


async def usage(session: AsyncSession, category: Category) -> Usage:
    ids = await subtree_ids(session, category)
    return Usage(
        transactions=await categories_repo.usage_counts(session, ids),
        children=len(ids) - 1,
        rules=await categories_repo.rules_count(session, ids),
    )


async def _resolve_replacement(
    session: AsyncSession, category: Category, subtree: list[str], move_to: str
) -> Category:
    target = await categories_repo.get(session, move_to)
    if target is None:
        raise CatalogError("категория для переноса не найдена")
    if target.id in subtree:
        raise CatalogError("нельзя перенести операции внутрь удаляемой категории")
    if target.kind != category.kind:
        raise CatalogError("перенести можно только в категорию того же типа")
    if target.archived:
        raise CatalogError("категория для переноса скрыта — сначала верните её в списки")
    return target


async def delete_category(
    session: AsyncSession, category: Category, *, move_to: str | None = None
) -> dict:
    """Удаляет категорию вместе с подкатегориями, предварительно перенеся операции.

    Удаление здесь настоящее, а не «спрятать»: скрытие никуда не делось, но это
    отдельное действие (`archived`), и путать их нельзя. Зато операция не может
    остаться без категории — если на поддереве что-то висит, вызывающий обязан
    сказать, куда это переносить. Молча обнулять `category_id` нельзя: отчёт за
    прошлые месяцы перестал бы сходиться с тем, что человек помнит.

    Переносятся и удалённые операции: они лежат в журнале и в таблице, и остаться
    со ссылкой на несуществующую категорию не должны.
    """
    subtree = await subtree_ids(session, category)
    used = await categories_repo.usage_counts(session, subtree)

    if used and not move_to:
        raise ReplacementRequired(
            f"на категории и её подкатегориях {used} операций — "
            "выберите, в какую категорию их перенести"
        )

    moved: list[str] = []
    if move_to:
        target = await _resolve_replacement(session, category, subtree, move_to)
        moved = await categories_repo.move_transactions(session, subtree, target.id)
        await categories_repo.move_rules(session, subtree, target.id)
        # Каждая перенесённая строка меняет колонку «Категория» в таблице — без этого
        # Google Sheets останется с прежними названиями до следующей полной перезаливки
        for tx_id in moved:
            await outbox_repo.enqueue(session, entity=TX_ENTITY, entity_id=tx_id)

    for child in await categories_repo.list_children(session, category.id):
        await categories_repo.remove(session, child)
    await categories_repo.remove(session, category)

    return {"result": "deleted", "moved": len(moved), "removed": len(subtree)}


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
