"""Периоды для отчётов.

Всё внутри — aware datetime в UTC. Границы полуинтервальные: [start, end).
"""

from datetime import UTC, date, datetime, timedelta

Period = tuple[datetime, datetime]


def now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def day_start(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


def month_start(value: date) -> date:
    return value.replace(day=1)


def add_months(value: date, months: int) -> date:
    total = value.year * 12 + (value.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def month_range(year: int, month: int) -> Period:
    start = date(year, month, 1)
    return day_start(start), day_start(add_months(start, 1))


def resolve_period(preset: str, today: date | None = None) -> Period:
    """Пресеты для UI: month, prev_month, week, 30d, year, all."""
    today = today or now().date()
    if preset == "month":
        return month_range(today.year, today.month)
    if preset == "prev_month":
        previous = add_months(month_start(today), -1)
        return month_range(previous.year, previous.month)
    if preset == "week":
        start = today - timedelta(days=today.weekday())
        return day_start(start), day_start(start + timedelta(days=7))
    if preset == "30d":
        return day_start(today - timedelta(days=29)), day_start(today + timedelta(days=1))
    if preset == "year":
        return day_start(date(today.year, 1, 1)), day_start(date(today.year + 1, 1, 1))
    if preset == "all":
        return datetime(1970, 1, 1, tzinfo=UTC), day_start(today + timedelta(days=1))
    raise ValueError(f"неизвестный период: {preset}")


def month_key(value: datetime) -> str:
    """'2026-08' — ключ группировки для помесячной аналитики."""
    return as_utc(value).strftime("%Y-%m")


# Раньше этой даты данных нет: журнал заводят вместе с приложением. Период,
# начинающийся здесь, — это «Всё время», и сравнивать его не с чем
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def previous_bounds(start: datetime, end: datetime) -> Period | None:
    """Предыдущий период той же природы — для сравнения «а как было раньше».

    Календарный месяц сдвигается календарно, а не на фиксированное число дней:
    в феврале двадцать восемь дней, и окно длиной в январь, отложенное назад,
    захватило бы кусок декабря — февраль после такого сравнения всегда выглядел бы
    дешевле, чем был.

    Для всего остального берём окно ровно той же длины, вплотную перед началом:
    неделя сравнивается с прошлой неделей, год с прошлым годом, произвольные
    десять дней — с предыдущими десятью.

    None означает «сравнивать не с чем»: у периода «Всё время» предыдущего нет.
    """
    begin, finish = as_utc(start), as_utc(end)
    if begin <= EPOCH:
        return None

    if begin == day_start(begin.date()) and begin.day == 1:
        if finish == day_start(add_months(begin.date(), 1)):
            previous = add_months(begin.date(), -1)
            return month_range(previous.year, previous.month)

    return begin - (finish - begin), begin
