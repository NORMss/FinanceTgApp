"""Разбор параметров периода из query string.

Один хелпер на все отчёты, чтобы `?period=month` и `?from=...&to=...` вели себя одинаково
в списке операций, в сводке и в экспорте.
"""

from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, Query, status

from app.util.dates import day_start, resolve_period


def period_bounds(
    period: str = Query("month", description="month | prev_month | week | 30d | year | all"),
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
) -> tuple[datetime, datetime]:
    """Явные from/to важнее пресета. Границы: [start, end), `to` включается целиком."""
    if date_from or date_to:
        if date_from and date_to and date_to < date_from:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "конец периода раньше начала")
        start = day_start(date_from) if date_from else datetime(1970, 1, 1, tzinfo=UTC)
        end = day_start((date_to or date.today()) + timedelta(days=1))
        return start, end

    try:
        return resolve_period(period)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
