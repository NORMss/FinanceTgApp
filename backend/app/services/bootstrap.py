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

# Подкатегории для тех корней, где разбивка нужна почти всем. Остальное пользователь
# добавит сам — заранее насыпать десятки магазинов смысла нет.
DEFAULT_SUBCATEGORIES: dict[str, list[tuple[str, str]]] = {
    "Продукты": [
        ("Пятёрочка", "🟢"),
        ("Магнит", "🔴"),
        ("ВкусВилл", "🥦"),
        ("Рынок", "🥕"),
    ],
    "Транспорт": [
        ("Такси", "🚕"),
        ("Общественный", "🚇"),
        ("Бензин", "⛽"),
    ],
    "Кафе и рестораны": [
        ("Кофе", "☕"),
        ("Доставка", "🛵"),
    ],
}

DEFAULT_INCOME_CATEGORIES: list[tuple[str, str]] = [
    ("Зарплата", "💼"),
    ("Подработка", "🧰"),
    ("Проценты", "🏦"),
    ("Возврат", "↩️"),
    ("Прочее", "📦"),
]

# Правила автокатегоризации: подстрока в тексте -> название категории.
# Покрывают типовой быстрый ввод из чата и дописываются руками по мере надобности.
# Где есть подкатегория, целимся в неё: «500 пятёрочка» из чата должно попасть
# в «Продукты · Пятёрочка», иначе разбивку пришлось бы проставлять руками.
DEFAULT_RULES: list[tuple[str, str]] = [
    ("пятёроч", "Пятёрочка"),
    ("пятероч", "Пятёрочка"),
    ("магнит", "Магнит"),
    ("перекрёст", "Продукты"),
    ("перекрест", "Продукты"),
    ("лента", "Продукты"),
    ("ашан", "Продукты"),
    ("вкусвилл", "ВкусВилл"),
    ("рынок", "Рынок"),
    ("продукт", "Продукты"),
    ("кофе", "Кофе"),
    ("кафе", "Кафе и рестораны"),
    ("ресторан", "Кафе и рестораны"),
    ("доставка", "Доставка"),
    ("такси", "Такси"),
    ("метро", "Общественный"),
    ("автобус", "Общественный"),
    ("бензин", "Бензин"),
    ("заправка", "Бензин"),
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
        roots: dict[str, Category] = {}
        for index, (name, icon) in enumerate(DEFAULT_EXPENSE_CATEGORIES):
            roots[name] = await categories_repo.create(
                session, name=name, kind=CategoryKind.EXPENSE, icon=icon, sort=index * 10
            )
        for parent_name, children in DEFAULT_SUBCATEGORIES.items():
            parent = roots.get(parent_name)
            if parent is None:
                continue
            for index, (name, icon) in enumerate(children):
                await categories_repo.create(
                    session,
                    name=name,
                    kind=CategoryKind.EXPENSE,
                    icon=icon,
                    parent_id=parent.id,
                    sort=index * 10,
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

    # Общий счёт здесь намеренно не заводится. Он не нейтрален: каждая трата с него
    # делится пополам и создаёт долг второму участнику, а по умолчанию таким счётом
    # пользовались просто потому, что он оказывался первым в списке. Теперь его заводят
    # руками — кнопкой в приложении, когда действительно есть общий кошелёк.
    await session.flush()


async def ensure_personal_account(session: AsyncSession, user: User) -> Account:
    """Личный счёт участника: и умолчание при вводе, и то, чем гасят долг переводом."""
    existing = await accounts_repo.get_personal(session, user.id)
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


async def ensure_shared_account(session: AsyncSession) -> Account:
    """Общий счёт — по требованию, а не при первом запуске.

    Идемпотентна: второй общий счёт завести нельзя, иначе «кто кому должен» пришлось бы
    считать по нескольким кошелькам сразу, а это уже не тот инструмент.
    """
    existing = await accounts_repo.get_shared(session)
    if existing is not None:
        return existing

    return await accounts_repo.create(
        session,
        name=SHARED_ACCOUNT_NAME,
        kind=AccountKind.CARD,
        currency=settings.base_currency,
        is_shared=True,
        sort=0,
    )
