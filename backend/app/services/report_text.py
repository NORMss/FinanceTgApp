"""Отчёт словами — для чата.

Одна и та же сводка попадает в чат двумя путями: командой `/month` из бота и кнопкой
«Отправить в чат» из приложения. Рендер обязан быть один: две реализации разошлись бы
на первой же правке, и один и тот же месяц выглядел бы по-разному в зависимости от
того, откуда его позвали.
"""

from datetime import date, datetime

from app.util.money import format_amount

# Два падежа: «Август 2026» заголовком и «1–14 августа» в диапазоне дат
NOMINATIVE = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)
GENITIVE = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
TOP_CATEGORIES = 7


def period_title(start: datetime, end: datetime) -> str:
    """«Август 2026» для календарного месяца, «1–14 августа» для остального.

    Название периода важнее, чем кажется: сводка уходит в чат и остаётся там
    навсегда, а «Расходы: 100 552» без даты через неделю не значит ничего.

    Граница `end` — правая открытая, поэтому последний день периода на сутки
    раньше: период «весь август» кончается первым сентября в ноль часов.
    """
    finish = date.fromordinal(end.date().toordinal() - 1)
    if start.day == 1 and (finish.month, finish.year) == (start.month, start.year):
        return f"{NOMINATIVE[start.month - 1]} {start.year}"
    if (finish.month, finish.year) == (start.month, start.year):
        return f"{start.day}–{finish.day} {GENITIVE[start.month - 1]}"
    return (
        f"{start.day} {GENITIVE[start.month - 1]} — {finish.day} {GENITIVE[finish.month - 1]}"
    )


def render(data: dict, start: datetime, end: datetime) -> str:
    """Сводка в HTML для Telegram. Пустые разделы не печатаются вовсе."""
    lines = [
        f"<b>{period_title(start, end)}</b>",
        f"Расходы: <b>{format_amount(data['expense_minor'])}</b>",
        f"Доходы: <b>{format_amount(data['income_minor'])}</b>",
        f"Сальдо: <b>{format_amount(data['net_minor'], sign=True)}</b>",
    ]

    if data.get("excluded_minor"):
        lines.append(f"<i>Скрыто исключениями: {format_amount(data['excluded_minor'])}</i>")

    previous = data.get("previous")
    if previous is not None and previous.expense_minor:
        delta = data["expense_minor"] - previous.expense_minor
        percent = round(delta / previous.expense_minor * 100)
        lines.append(
            f"К прошлому периоду: <b>{format_amount(delta, sign=True)}</b> ({percent:+d}%)"
        )

    if data["by_category"]:
        lines.append("\n<b>Топ категорий</b>")
        # Только корневые: подкатегории уже сложены в родителя, и печатать их
        # следом значит показать одни и те же деньги дважды
        roots = [item for item in data["by_category"] if not item.parent_id][:TOP_CATEGORIES]
        for item in roots:
            share = round(item.share * 100)
            label = f"{item.icon} {item.name}".strip()
            lines.append(f"{label} — {format_amount(item.amount_minor)} ({share}%)")

    if len(data["by_author"]) > 1:
        lines.append("\n<b>Кто сколько потратил</b>")
        lines += [
            f"{row['name']} — {format_amount(row['amount_minor'])}" for row in data["by_author"]
        ]

    return "\n".join(lines)
