"""Демонстрационные данные: журнал семьи из двух человек за три месяца.

    python -m app.demo --reset

Зачем отдельный модуль, а не пара строк в тестах: пустое приложение невозможно
показать. Отчёт без операций — три нуля, история — надпись «за этот период операций
нет», взаиморасчёты — «все в расчёте». Чтобы человек за минуту понял, что тут вообще
происходит, нужен правдоподобный журнал: разные категории и подкатегории, обе роли
плательщика, зарплаты, погашение долга переводом.

Данные детерминированные (фиксированный seed) — скриншоты в README не разъезжаются
от запуска к запуску. Даты считаются от сегодняшнего дня, поэтому период «Месяц»
всегда что-то показывает, в каком бы году демо ни запустили.
"""

import argparse
import asyncio
import random
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import dispose_engine, get_session_factory
from app.models import (
    Account,
    SyncOutbox,
    Transaction,
    TransactionType,
    TxSource,
    TxSplit,
    User,
)
from app.repositories import accounts as accounts_repo
from app.repositories import categories as categories_repo
from app.repositories import users as users_repo
from app.security.initdata import TelegramUser
from app.services import bootstrap, ledger
from app.util.dates import now

SEED = 20260816
DEMO_IDS = (900_000_001, 900_000_002)
LOCAL_TZ = datetime.now().astimezone().tzinfo


@dataclass(frozen=True, slots=True)
class Pattern:
    """Как часто и на сколько тратят в этой категории.

    Вероятность — на день. `weekend` поднимает шанс в выходные: кафе и развлечения
    в субботу случаются чаще, чем во вторник, и без этого график выглядит
    сгенерированным.
    """

    category: str
    chance: float
    low: int
    high: int
    notes: tuple[str, ...] = ()
    weekend: float = 1.0


# Суммы в рублях. Порядок величин взят бытовой: продукты через день,
# коммуналка раз в месяц, крупные покупки редкие.
PATTERNS = (
    Pattern("Пятёрочка", 0.45, 350, 2600, ("молоко, хлеб", "на неделю", "")),
    Pattern("Магнит", 0.18, 200, 1500, ("по мелочи", "")),
    Pattern("ВкусВилл", 0.14, 400, 2200, ("завтраки", "")),
    Pattern("Рынок", 0.08, 500, 3000, ("овощи и фрукты", "")),
    Pattern("Кофе", 0.35, 150, 500, ("с собой", "")),
    Pattern("Доставка", 0.12, 700, 2500, ("ужин", "пицца"), weekend=2.0),
    Pattern("Кафе и рестораны", 0.10, 1200, 5500, ("вдвоём", "с друзьями"), weekend=2.5),
    Pattern("Такси", 0.16, 250, 900, ("до дома", "")),
    Pattern("Общественный", 0.30, 60, 180, ()),
    Pattern("Бензин", 0.07, 1800, 3500, ("полный бак", "")),
    Pattern("Здоровье", 0.06, 400, 4500, ("аптека", "приём врача")),
    Pattern("Развлечения", 0.07, 600, 3500, ("кино", "концерт"), weekend=2.5),
    Pattern("Одежда", 0.05, 1500, 9000, ("кроссовки", "куртка")),
    Pattern("Подарки", 0.03, 1000, 6000, ("на день рождения",)),
    Pattern("Прочее", 0.08, 200, 2000, ()),
)

# Раз в месяц, в указанный день. Последнее поле — кто платит: 0, 1 или «по очереди».
# Аренда — самая крупная строка бюджета, и если её всегда вносит один человек,
# «кто кому должен» показывает шестизначный долг вместо бытовой суммы
MONTHLY = (
    ("Жильё и коммуналка", 5, 38_000, "аренда", "alternate"),
    ("Жильё и коммуналка", 12, 4_200, "коммуналка", 1),
    ("Связь и интернет", 8, 1_100, "интернет и связь", 1),
    ("Развлечения", 3, 999, "подписки", 0),
)

SALARIES = (
    (0, 10, 185_000, "зарплата"),  # (индекс участника, день месяца, сумма, заметка)
    (1, 25, 142_000, "зарплата"),
)


class DemoError(RuntimeError):
    """Что-то мешает наполнить демо — например, в базе уже есть настоящие данные."""


def _at(day: datetime, hour: int, minute: int = 0) -> datetime:
    """Момент по часам местного пояса, сохранённый как UTC.

    В базе всё лежит в UTC, а на экране показывается в поясе зрителя. Если ставить
    час прямо в UTC, то в Москве продукты «покупаются» в три ночи, а в Новосибирске —
    в пять утра. Считаем от местной зоны той машины, где запущено демо: там его и смотрят.
    """
    local = day.astimezone(LOCAL_TZ).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return local.astimezone(UTC)


async def _has_data(session: AsyncSession) -> bool:
    result = await session.execute(select(func.count()).select_from(Transaction))
    return int(result.scalar_one()) > 0


async def _wipe(session: AsyncSession) -> None:
    """Чистит журнал, счета и участников, оставляя справочник категорий.

    Порядок задан руками и он важен: между Transaction и Account нет ORM-связи,
    только внешний ключ в базе, поэтому SQLAlchemy сам не догадается удалять операции
    раньше счетов — и упрётся в RESTRICT.
    """
    for model in (TxSplit, SyncOutbox, Transaction, Account, User):
        await session.execute(sql_delete(model))
    await session.flush()


async def _ensure_people(session: AsyncSession) -> list[User]:
    people = []
    for telegram_id, name in zip(DEMO_IDS, ("Аня", "Борис"), strict=True):
        user = await users_repo.upsert_from_telegram(
            session, TelegramUser(id=telegram_id, first_name=name)
        )
        await bootstrap.ensure_personal_account(session, user)
        people.append(user)
    return people


async def seed(session: AsyncSession, *, months: int = 3, reset: bool = False) -> dict:
    if await _has_data(session):
        if not reset:
            raise DemoError(
                "в базе уже есть операции — демо не станет их затирать.\n"
                "Запустите с --reset, если это действительно демо-база."
            )
        await _wipe(session)

    rng = random.Random(SEED)

    await bootstrap.ensure_reference_data(session)
    people = await _ensure_people(session)
    # Общий счёт приложение само не заводит — а демо показывает именно совместный
    # бюджет, поэтому здесь он создаётся явно
    shared = await bootstrap.ensure_shared_account(session)

    personal = {user.id: await accounts_repo.get_personal(session, user.id) for user in people}

    categories = {
        category.name: category
        for category in await categories_repo.list_all(session, include_archived=True)
    }

    today = now().replace(hour=12, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=months * 30)
    created = 0

    day = start
    while day <= today:
        weekend = day.weekday() >= 5

        for pattern in PATTERNS:
            chance = pattern.chance * (pattern.weekend if weekend else 1.0)
            if rng.random() > chance:
                continue
            category = categories.get(pattern.category)
            if category is None:
                continue

            # Ровно поровну: перекос в 5% на трёхстах операциях даёт долг в десятки
            # тысяч, и раздел «кто кому должен» выглядит поломанным, а не полезным
            author = people[0] if rng.random() < 0.5 else people[1]
            amount = rng.randint(pattern.low, pattern.high)
            # Круглые суммы в жизни редкость, но и копейки не у каждой траты
            minor = amount * 100 - (rng.choice((0, 0, 0, 1, 10, 50, 90)))
            moment = _at(day, rng.randint(8, 22), rng.choice((0, 5, 12, 17, 23, 31, 45, 58)))
            await ledger.create_transaction(
                session,
                author=author,
                tx_type=TransactionType.EXPENSE,
                amount_minor=max(minor, 100),
                account_id=shared.id,
                category_id=category.id,
                occurred_at=moment,
                note=rng.choice(pattern.notes) if pattern.notes else "",
                source=rng.choice((TxSource.APP, TxSource.APP, TxSource.BOT)),
            )
            created += 1

        for category_name, day_of_month, amount, note, payer in MONTHLY:
            if day.day != day_of_month:
                continue
            category = categories.get(category_name)
            if category is None:
                continue
            index = day.month % 2 if payer == "alternate" else payer
            await ledger.create_transaction(
                session,
                author=people[index],
                tx_type=TransactionType.EXPENSE,
                amount_minor=amount * 100,
                account_id=shared.id,
                category_id=category.id,
                occurred_at=_at(day, 10),
                note=note,
            )
            created += 1

        for index, day_of_month, amount, note in SALARIES:
            if day.day != day_of_month:
                continue
            user = people[index]
            await ledger.create_transaction(
                session,
                author=user,
                tx_type=TransactionType.INCOME,
                amount_minor=amount * 100,
                account_id=personal[user.id].id if personal[user.id] else shared.id,
                category_id=categories["Зарплата"].id,
                occurred_at=_at(day, 11),
                note=note,
            )
            created += 1

            # После зарплаты — перевод на общий счёт, обычное семейное «скидываемся»
            if personal[user.id]:
                await ledger.create_transaction(
                    session,
                    author=user,
                    tx_type=TransactionType.TRANSFER,
                    amount_minor=(amount // 2) * 100,
                    account_id=personal[user.id].id,
                    counter_account_id=shared.id,
                    occurred_at=_at(day, 11, 30),
                    note="в общий котёл",
                )
                created += 1

        day += timedelta(days=1)

    await session.commit()
    return {"transactions": created, "people": [user.display_name for user in people]}


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Наполнить базу демонстрационными данными")
    parser.add_argument("--reset", action="store_true", help="стереть существующий журнал")
    parser.add_argument("--months", type=int, default=3, help="за сколько месяцев (по умолчанию 3)")
    args = parser.parse_args(argv)

    try:
        async with get_session_factory()() as session:
            result = await seed(session, months=args.months, reset=args.reset)
    except DemoError as exc:
        print(f"Демо не заполнено: {exc}", file=sys.stderr)
        return 1
    finally:
        await dispose_engine()

    print(
        f"Готово: {result['transactions']} операций за {args.months} мес., "
        f"участники — {', '.join(result['people'])}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
