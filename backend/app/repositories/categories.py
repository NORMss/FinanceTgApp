from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, CategoryKind, CategoryRule, Transaction


async def get(session: AsyncSession, category_id: str) -> Category | None:
    return await session.get(Category, category_id)


async def list_all(
    session: AsyncSession,
    *,
    kind: CategoryKind | None = None,
    include_archived: bool = False,
) -> list[Category]:
    query = select(Category).order_by(Category.sort, Category.name)
    if kind is not None:
        query = query.where(Category.kind == kind)
    if not include_archived:
        query = query.where(Category.archived.is_(False))
    result = await session.execute(query)
    return list(result.scalars())


async def get_by_name(
    session: AsyncSession,
    name: str,
    *,
    kind: CategoryKind | None = None,
    parent_id: str | None = None,
    root_only: bool = False,
) -> Category | None:
    query = select(Category).where(Category.name.ilike(name.strip()))
    if kind is not None:
        query = query.where(Category.kind == kind)
    if parent_id is not None:
        query = query.where(Category.parent_id == parent_id)
    elif root_only:
        query = query.where(Category.parent_id.is_(None))
    result = await session.execute(query.limit(1))
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    name: str,
    kind: CategoryKind = CategoryKind.EXPENSE,
    icon: str = "",
    parent_id: str | None = None,
    sort: int = 100,
) -> Category:
    category = Category(name=name.strip(), kind=kind, icon=icon, parent_id=parent_id, sort=sort)
    session.add(category)
    await session.flush()
    return category


async def list_children(session: AsyncSession, parent_id: str) -> list[Category]:
    query = (
        select(Category)
        .where(Category.parent_id == parent_id)
        .order_by(Category.sort, Category.name)
    )
    result = await session.execute(query)
    return list(result.scalars())


async def usage_count(session: AsyncSession, category_id: str) -> int:
    """Сколько живых операций ссылается на категорию. Ноль — можно удалять насовсем."""
    query = select(func.count(Transaction.id)).where(
        Transaction.category_id == category_id,
        Transaction.deleted_at.is_(None),
    )
    result = await session.execute(query)
    return int(result.scalar_one())


async def remove(session: AsyncSession, category: Category) -> None:
    """Физическое удаление. Вызывать только для категории без операций и без детей."""
    await session.execute(sql_delete(CategoryRule).where(CategoryRule.category_id == category.id))
    await session.delete(category)
    await session.flush()


async def list_rules(session: AsyncSession) -> list[CategoryRule]:
    result = await session.execute(select(CategoryRule).order_by(CategoryRule.priority))
    return list(result.scalars())


async def add_rule(
    session: AsyncSession, *, pattern: str, category_id: str, priority: int = 100
) -> CategoryRule:
    rule = CategoryRule(pattern=pattern.strip().lower(), category_id=category_id, priority=priority)
    session.add(rule)
    await session.flush()
    return rule


async def bump_rule_hits(session: AsyncSession, rule_id: str) -> None:
    await session.execute(
        update(CategoryRule)
        .where(CategoryRule.id == rule_id)
        .values(hits=CategoryRule.hits + 1)
    )
