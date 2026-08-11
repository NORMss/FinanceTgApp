"""Начальное наполнение: справочники и счета.

Вызывается на старте приложения и при первом входе пользователя. Все операции
идемпотентны — повторный запуск ничего не дублирует.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Account, AccountKind, Category, CategoryKind, CategoryRule, User
from app.repositories import accounts as accounts_repo
from app.repositories import categories as categories_repo

DEFAULT_EXPENSE_CATEGORIES: list[tuple[str, str]] = [
    ("Продукты", "🛒"),
    ("Кафе и рестораны", "🍽"),
    ("Транспорт", "🚌"),
    ("Жильё и коммуналка", "🏠"),
    ("Здоровье", "💊"),
    ("Развлечения", "🎬"),
    ("Одежда", "👕"),
    ("Связь и интернет", "📶"),
    ("Подарки", "🎁"),
    ("Прочее", "📦"),
]

DEFAULT_INCOME_CATEGORIES: list[tuple[str, str]] = [
    ("Зарплата", "💼"),
    ("Подработка", "🧰"),
    ("Проценты", "🏦"),
    ("Возврат", "↩️"),
    ("Прочее", "📦"),
]

# Правила автокатегоризации: подстрока в тексте -> название категории.
# Покрывают типовой быстрый ввод из чата и дописываются руками по мере надобности.
DEFAULT_RULES: list[tuple[str, str]] = [
    ("пятёроч", "Продукты"),
    ("пятероч", "Продукты"),
    ("магнит", "Продукты"),
    ("перекрёст", "Продукты"),
    ("перекрест", "Продукты"),
    ("лента", "Продукты"),
    ("ашан", "Продукты"),
    ("вкусвилл", "Продукты"),
    ("продукт", "Продукты"),
    ("кофе", "Кафе и рестораны"),
    ("кафе", "Кафе и рестораны"),
    ("ресторан", "Кафе и рестораны"),
    ("доставка", "Кафе и рестораны"),
    ("такси", "Транспорт"),
    ("метро", "Транспорт"),
    ("бензин", "Транспорт"),
    ("заправка", "Транспорт"),
    ("аренда", "Жильё и коммуналка"),
    ("квартплата", "Жильё и коммуналка"),
    ("жкх", "Жильё и коммуналка"),
    ("аптек", "Здоровье"),
    ("врач", "Здоровье"),
    ("кино", "Развлечения"),
    ("подписк", "Связь и интернет"),
    ("интернет", "Связь и интернет"),
    ("связь", "Связь и интернет"),
]

SHARED_ACCOUNT_NAME = "Общий счёт"


async def _is_empty(session: AsyncSession, model: type) -> bool:
    result = await session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one()) == 0


async def ensure_reference_data(session: AsyncSession) -> None:
    """Создаёт категории, правила и общий счёт, если база ещё пустая."""
    if await _is_empty(session, Category):
        for index, (name, icon) in enumerate(DEFAULT_EXPENSE_CATEGORIES):
            await categories_repo.create(
                session, name=name, kind=CategoryKind.EXPENSE, icon=icon, sort=index * 10
            )
        for index, (name, icon) in enumerate(DEFAULT_INCOME_CATEGORIES):
            await categories_repo.create(
                session, name=name, kind=CategoryKind.INCOME, icon=icon, sort=index * 10
            )

    if await _is_empty(session, CategoryRule):
        by_name = {
            category.name: category
            for category in await categories_repo.list_all(session, kind=CategoryKind.EXPENSE)
        }
        for pattern, category_name in DEFAULT_RULES:
            category = by_name.get(category_name)
            if category is not None:
                await categories_repo.add_rule(
                    session, pattern=pattern, category_id=category.id, priority=50
                )

    if await accounts_repo.get_shared(session) is None and await _is_empty(session, Account):
        await accounts_repo.create(
            session,
            name=SHARED_ACCOUNT_NAME,
            kind=AccountKind.CARD,
            currency=settings.base_currency,
            is_shared=True,
            sort=0,
        )

    await session.flush()


async def ensure_personal_account(session: AsyncSession, user: User) -> Account:
    """У каждого участника должен быть личный счёт: без него не сделать перевод-погашение."""
    result = await session.execute(
        select(Account).where(Account.owner_id == user.id, Account.is_shared.is_(False)).limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing

    return await accounts_repo.create(
        session,
        name=f"Личный · {user.display_name}",
        kind=AccountKind.CASH,
        currency=settings.base_currency,
        owner_id=user.id,
        sort=10,
    )
