"""Разбор строки быстрого ввода: «500 продукты пятёрочка».

Это главный способ ввода в повседневности — набрать одну строку в чат быстрее,
чем открыть Mini App. Формат намеренно свободный:

    500 продукты            -> расход 500 в категорию «Продукты»
    1 200,50 такси домой    -> расход 1200.50, категория «Транспорт», заметка «такси домой»
    +50000 зарплата         -> доход 50000 в категорию «Зарплата»
    350                     -> расход 350 без категории

Категория определяется в два прохода: сначала точное/префиксное совпадение с названием,
потом правила автокатегоризации по подстроке.
"""

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CategoryKind, TransactionType
from app.repositories import categories as categories_repo
from app.util.money import to_minor

_AMOUNT_RE = re.compile(
    r"^\s*(?P<sign>[+-])?\s*(?P<amount>\d[\d\s  ]*(?:[.,]\d{1,2})?)\s*(?P<rest>.*)$",
    re.DOTALL,
)


class ParseError(ValueError):
    """Строку не удалось разобрать — бот отвечает подсказкой по формату."""


@dataclass(slots=True)
class ParsedEntry:
    amount_minor: int
    tx_type: TransactionType
    category_id: str | None
    category_name: str | None
    note: str
    matched_rule_id: str | None = None


async def parse(session: AsyncSession, text: str, *, currency: str = "RUB") -> ParsedEntry:
    match = _AMOUNT_RE.match(text or "")
    if not match:
        raise ParseError("не вижу сумму в начале строки")

    raw_amount = match.group("amount")
    try:
        amount_minor = to_minor(raw_amount, currency)
    except ValueError as exc:
        raise ParseError(str(exc)) from exc
    if amount_minor <= 0:
        raise ParseError("сумма должна быть больше нуля")

    tx_type = TransactionType.INCOME if match.group("sign") == "+" else TransactionType.EXPENSE
    rest = match.group("rest").strip()
    kind = CategoryKind.INCOME if tx_type == TransactionType.INCOME else CategoryKind.EXPENSE

    category_id: str | None = None
    category_name: str | None = None
    rule_id: str | None = None
    note = rest

    if rest:
        categories = await categories_repo.list_all(session, kind=kind)
        lowered = rest.lower()

        # 1) название категории целиком или её первое слово
        for category in categories:
            name = category.name.lower()
            if lowered == name or lowered.startswith(f"{name} "):
                category_id, category_name = category.id, category.name
                note = rest[len(category.name) :].strip()
                break
            first_word = name.split()[0]
            if len(first_word) >= 4 and (
                lowered == first_word or lowered.startswith(f"{first_word} ")
            ):
                category_id, category_name = category.id, category.name
                note = rest[len(first_word) :].strip()
                break

        # 2) правила по подстроке
        if category_id is None:
            catalog = {category.id: category for category in categories}
            for rule in await categories_repo.list_rules(session):
                if rule.pattern and rule.pattern in lowered and rule.category_id in catalog:
                    category_id = rule.category_id
                    category_name = catalog[rule.category_id].name
                    rule_id = rule.id
                    break

    return ParsedEntry(
        amount_minor=amount_minor,
        tx_type=tx_type,
        category_id=category_id,
        category_name=category_name,
        note=note.strip(),
        matched_rule_id=rule_id,
    )
