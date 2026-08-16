"""Ежедневное напоминание внести траты.

Правило одно: если к назначенному часу человек ничего не записал за сегодняшний день,
бот пишет ему одно сообщение. Записал сам, или напоминание уже уходило — молчим.

Всё считается в местном поясе пользователя, а не сервера: «21:00» должно быть его
девятью вечера. Пояс приходит из браузера при входе в Mini App (IANA-имя вроде
`Europe/Moscow`), потому что смещение в минутах сломалось бы при переходе на летнее время.

Здесь нет ни одного вызова Telegram: модуль решает, кому пора, а отправкой занимается
app.bot.notify. Так логику можно проверить тестами, не поднимая бота.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User
from app.repositories import transactions as tx_repo
from app.repositories import users as users_repo
from app.repositories.transactions import TxFilter
from app.util.dates import now

log = logging.getLogger(__name__)

DEFAULT_TIME = "21:00"


class ReminderError(ValueError):
    """Настройка не годится: непонятное время или незнакомый часовой пояс."""


@dataclass(frozen=True, slots=True)
class Due:
    """Кому пора напомнить и за какой его местный день."""

    user: User
    local_date: date


def parse_time(raw: str) -> time:
    """«21:00», «9:5», «07:30» -> time. Секунды и любой мусор отвергаем.

    Формат сознательно узкий: значение приходит из <input type="time">, который отдаёт
    ровно «HH:MM», и всё остальное — это либо ошибка клиента, либо попытка подсунуть
    что-то в базу.
    """
    parts = raw.strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ReminderError("время указывается как ЧЧ:ММ, например 21:00")
    hour, minute = (int(part) for part in parts)
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ReminderError("такого времени не бывает")
    return time(hour, minute)


def format_time(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def parse_tz(name: str) -> ZoneInfo:
    """Имя зоны IANA -> ZoneInfo. Пустая строка означает зону по умолчанию."""
    candidate = name.strip() or settings.default_timezone
    try:
        return ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ReminderError(f"неизвестный часовой пояс: {candidate}") from exc


def user_tz(user: User) -> ZoneInfo:
    """Пояс пользователя, а при испорченном значении — UTC.

    Падать здесь нельзя: это фоновая рассылка, и одна кривая строка в базе не должна
    останавливать напоминания всем остальным.
    """
    try:
        return parse_tz(user.reminder_tz)
    except ReminderError:
        log.warning("непонятный пояс «%s» у %s, считаю в UTC", user.reminder_tz, user.id)
        return ZoneInfo("UTC")


def local_day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Сутки местного пояса в виде границ [start, end) в UTC — как их хранит база."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


def due_date(user: User, moment: datetime) -> date | None:
    """Местная дата, за которую пора напомнить, либо None.

    Сравниваем не «сейчас ровно 21:00», а «уже не раньше 21:00»: планировщик может
    пропустить минуту из-за перезапуска контейнера, и напоминание тогда просто уйдёт
    чуть позже. Верхняя граница получается сама собой — местная полночь, после которой
    наступает уже другая дата.
    """
    if not user.reminder_enabled or not user.is_active:
        return None

    try:
        target = parse_time(user.reminder_time)
    except ReminderError:
        log.warning("непонятное время «%s» у %s", user.reminder_time, user.id)
        return None

    local = moment.astimezone(user_tz(user))
    if (local.hour, local.minute) < (target.hour, target.minute):
        return None
    if user.reminder_last_sent_on == local.date():
        return None
    return local.date()


async def has_entries_for(session: AsyncSession, user: User, day: date) -> bool:
    """Есть ли у человека операции, датированные этим его местным днём.

    Считаем именно по дате операции, а не по времени создания записи: напоминание
    просит внести траты за день, и вчерашний чек, добавленный сегодня, эту просьбу
    не закрывает.
    """
    start, end = local_day_bounds(day, user_tz(user))
    count = await tx_repo.count(session, TxFilter(start=start, end=end, author_ids=[user.id]))
    return count > 0


async def pending(session: AsyncSession, moment: datetime | None = None) -> list[Due]:
    """Кому прямо сейчас нужно отправить напоминание."""
    if not settings.reminders_enabled:
        return []

    moment = moment or now()
    result: list[Due] = []
    for user in await users_repo.list_all(session):
        # Того, кого убрали из белого списка, беспокоить не за чем — доступа у него уже нет
        if not settings.dev_auth_bypass and not settings.is_allowed(user.telegram_id):
            continue
        day = due_date(user, moment)
        if day is None:
            continue
        if await has_entries_for(session, user, day):
            continue
        result.append(Due(user=user, local_date=day))
    return result


def mark_sent(item: Due) -> None:
    """Отмечает, что за этот местный день напоминание уже ушло."""
    item.user.reminder_last_sent_on = item.local_date


async def update_settings(
    session: AsyncSession,
    user: User,
    *,
    enabled: bool | None = None,
    at: str | None = None,
    tz: str | None = None,
) -> User:
    """Меняет настройку напоминания. Присылать можно любое подмножество полей."""
    if at is not None:
        user.reminder_time = format_time(parse_time(at))
    if tz is not None:
        parse_tz(tz)  # проверяем до записи: неизвестная зона в базе — это молчащие напоминания
        user.reminder_tz = tz.strip()[:64]
    if enabled is not None:
        # Отметку о последней отправке намеренно не трогаем: иначе выключить и включить
        # обратно вечером означало бы получить второе напоминание за тот же день
        user.reminder_enabled = enabled

    await session.flush()
    return user


def remember_timezone(user: User, tz: str) -> bool:
    """Запоминает пояс, присланный клиентом при входе. True, если значение изменилось.

    Вызывается на каждом входе в Mini App: человек переезжает, меняет телефон, летит
    в отпуск — и напоминание должно ехать за ним, а не оставаться в поясе первого входа.
    """
    candidate = tz.strip()
    if not candidate or candidate == user.reminder_tz:
        return False
    try:
        parse_tz(candidate)
    except ReminderError:
        log.info("клиент прислал неизвестный пояс: %s", candidate[:64])
        return False
    user.reminder_tz = candidate[:64]
    return True
