"""Компактный дамп для языковой модели.

Осознанно выгружаем не строки, а агрегаты: месяц × категория, месяц × участник и топ
повторяющихся заметок. Такой дамп на год умещается в пару тысяч токенов, тогда как сырой
журнал за тот же год — десятки тысяч, и модель в нём тонет.
"""

from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import TransactionType
from app.repositories import accounts as accounts_repo
from app.repositories import transactions as tx_repo
from app.repositories import users as users_repo
from app.repositories.transactions import TxFilter
from app.services import stats as stats_service
from app.util.dates import month_key
from app.util.money import to_major


async def build_dump(session: AsyncSession, flt: TxFilter) -> dict:
    matrix = await stats_service.monthly_by_category(session, flt)
    months: list[str] = matrix["months"]
    categories: dict[str, dict[str, int]] = matrix["categories"]

    users = {user.id: user.display_name for user in await users_repo.list_all(session)}
    # Разрез по людям — «за кого потратили», а не «кто ввёл»: трату за другого пишут
    # на его личный счёт, и в его строке она и должна оказаться
    owners = {
        account.id: account.owner_id
        for account in await accounts_repo.list_all(session, include_archived=True)
    }
    by_user_month: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    notes: dict[str, list[int]] = defaultdict(list)
    income_by_month: dict[str, int] = defaultdict(int)
    expense_by_month: dict[str, int] = defaultdict(int)

    # Один проход по журналу: заметки и разрезы по людям в агрегатах SQL не собрать дёшево
    offset = 0
    while True:
        page = await tx_repo.list_page(session, flt, limit=500, offset=offset)
        if not page:
            break
        for tx in page:
            key = month_key(tx.occurred_at)
            if tx.type == TransactionType.EXPENSE:
                expense_by_month[key] += tx.amount_minor
                person_id = owners.get(tx.account_id) or tx.author_id
                by_user_month[users.get(person_id, "?")][key] += tx.amount_minor
                if tx.note:
                    notes[tx.note.strip().lower()].append(tx.amount_minor)
            elif tx.type == TransactionType.INCOME:
                income_by_month[key] += tx.amount_minor
        offset += len(page)

    top_notes = sorted(
        ((note, len(amounts), sum(amounts)) for note, amounts in notes.items() if len(amounts) > 1),
        key=lambda row: row[2],
        reverse=True,
    )[:25]

    return {
        "currency": settings.base_currency,
        "months": months,
        "totals": [
            {
                "month": month,
                "income": str(to_major(income_by_month.get(month, 0))),
                "expense": str(to_major(expense_by_month.get(month, 0))),
                "net": str(
                    to_major(income_by_month.get(month, 0) - expense_by_month.get(month, 0))
                ),
            }
            for month in months
        ],
        "by_category": {
            name: {month: str(to_major(values.get(month, 0))) for month in months}
            for name, values in categories.items()
        },
        "by_user": {
            name: {month: str(to_major(values.get(month, 0))) for month in months}
            for name, values in by_user_month.items()
        },
        "recurring_notes": [
            {"note": note, "count": count, "total": str(to_major(total))}
            for note, count, total in top_notes
        ],
    }


def render_markdown(dump: dict) -> str:
    """Тот же дамп текстом — его удобно просто вставить в чат с моделью."""
    months = dump["months"]
    currency = dump["currency"]
    lines: list[str] = [
        "# Дамп расходов домохозяйства",
        f"Валюта: {currency}. Все суммы — в основных единицах.",
        f"Месяцы: {', '.join(months) if months else 'нет данных'}",
        "",
        "## Итоги по месяцам",
        "| месяц | доходы | расходы | сальдо |",
        "| --- | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {row['month']} | {row['income']} | {row['expense']} | {row['net']} |"
        for row in dump["totals"]
    ]

    header = "| категория | " + " | ".join(months) + " | итого |"
    lines += ["", "## Расходы по категориям", header]
    lines.append("| --- |" + " ---: |" * (len(months) + 1))
    for name, values in sorted(
        dump["by_category"].items(),
        key=lambda item: sum(float(v) for v in item[1].values()),
        reverse=True,
    ):
        total = sum(float(v) for v in values.values())
        cells = " | ".join(values.get(month, "0") for month in months)
        lines.append(f"| {name} | {cells} | {total:.2f} |")

    if dump["by_user"]:
        lines += ["", "## Расходы по участникам", "| участник | " + " | ".join(months) + " |"]
        lines.append("| --- |" + " ---: |" * len(months))
        for name, values in dump["by_user"].items():
            cells = " | ".join(values.get(month, "0") for month in months)
            lines.append(f"| {name} | {cells} |")

    if dump["recurring_notes"]:
        lines += ["", "## Повторяющиеся траты", "| заметка | раз | сумма |"]
        lines.append("| --- | ---: | ---: |")
        lines += [
            f"| {row['note']} | {row['count']} | {row['total']} |"
            for row in dump["recurring_notes"]
        ]

    lines += [
        "",
        "## Задача для модели",
        "Найди категории и повторяющиеся траты, которые можно сократить без потери качества жизни.",
        "Для каждой рекомендации укажи оценку экономии в месяц и на чём она основана.",
    ]
    return "\n".join(lines)
