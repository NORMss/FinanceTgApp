"""Ежедневное напоминание: кому, когда и в каком поясе.

Главное, что проверяется, — арифметика поясов. «21:00» у человека в Новосибирске
и у человека в Москве — это два разных момента UTC, а «сегодня» у них заканчивается
в разное время, и траты за день надо искать в его сутках, а не в серверных.
"""

from datetime import UTC, date, datetime

import httpx
import pytest
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy.ext.asyncio import AsyncSession

from app import scheduler
from app.bot import notify
from app.models import TransactionType, User
from app.repositories import accounts as accounts_repo
from app.repositories import users as users_repo
from app.security.initdata import TelegramUser, build_init_data
from app.services import bootstrap, ledger
from app.services import reminders as reminders_service

TOKEN = "123456:TEST-TOKEN"
MSK = "Europe/Moscow"  # UTC+3, без перехода на летнее время
NSK = "Asia/Novosibirsk"  # UTC+7


async def _person(
    session: AsyncSession,
    telegram_id: int = 111,
    *,
    name: str = "Аня",
    tz: str = MSK,
    at: str = "21:00",
    enabled: bool = True,
) -> User:
    await bootstrap.ensure_reference_data(session)
    user = await users_repo.upsert_from_telegram(
        session, TelegramUser(id=telegram_id, first_name=name)
    )
    await bootstrap.ensure_personal_account(session, user)
    user.reminder_tz = tz
    user.reminder_time = at
    user.reminder_enabled = enabled
    await session.flush()
    return user


async def _spend(session: AsyncSession, user: User, moment: datetime) -> None:
    account = await accounts_repo.default_for(session, user.id)
    await ledger.create_transaction(
        session,
        author=user,
        tx_type=TransactionType.EXPENSE,
        amount_minor=50_000,
        account_id=account.id,
        occurred_at=moment,
    )


# --- разбор настроек ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("21:00", "21:00"), ("9:5", "09:05"), (" 07:30 ", "07:30"), ("00:00", "00:00")],
)
def test_parse_time_normalizes(raw: str, expected: str):
    assert reminders_service.format_time(reminders_service.parse_time(raw)) == expected


@pytest.mark.parametrize("raw", ["25:00", "21:60", "21", "21:00:00", "вечером", "", "-1:00"])
def test_parse_time_rejects_garbage(raw: str):
    with pytest.raises(reminders_service.ReminderError):
        reminders_service.parse_time(raw)


def test_unknown_timezone_is_rejected():
    with pytest.raises(reminders_service.ReminderError):
        reminders_service.parse_tz("Europe/Атлантида")


# --- когда пора ---


async def test_not_due_before_the_hour(session: AsyncSession):
    user = await _person(session)
    # 17:59 UTC — это 20:59 в Москве, ещё рано
    assert reminders_service.due_date(user, datetime(2026, 8, 17, 17, 59, tzinfo=UTC)) is None


async def test_due_after_the_hour(session: AsyncSession):
    user = await _person(session)
    moment = datetime(2026, 8, 17, 18, 5, tzinfo=UTC)  # 21:05 в Москве
    assert reminders_service.due_date(user, moment) == date(2026, 8, 17)


async def test_same_moment_is_not_due_in_another_timezone(session: AsyncSession):
    """21:05 в Москве — это 01:05 следующих суток в Новосибирске, и напоминать рано."""
    user = await _person(session, tz=NSK)
    assert reminders_service.due_date(user, datetime(2026, 8, 17, 18, 5, tzinfo=UTC)) is None

    # А в 14:05 UTC у него уже 21:05, и дата — тоже 17-е
    assert reminders_service.due_date(
        user, datetime(2026, 8, 17, 14, 5, tzinfo=UTC)
    ) == date(2026, 8, 17)


async def test_disabled_is_never_due(session: AsyncSession):
    user = await _person(session, enabled=False)
    assert reminders_service.due_date(user, datetime(2026, 8, 17, 20, 0, tzinfo=UTC)) is None


async def test_already_sent_today_is_not_due_again(session: AsyncSession):
    user = await _person(session)
    moment = datetime(2026, 8, 17, 18, 5, tzinfo=UTC)
    user.reminder_last_sent_on = date(2026, 8, 17)
    assert reminders_service.due_date(user, moment) is None
    # Но завтра — снова
    assert reminders_service.due_date(
        user, datetime(2026, 8, 18, 18, 5, tzinfo=UTC)
    ) == date(2026, 8, 18)


async def test_broken_settings_do_not_raise(session: AsyncSession):
    """Кривые данные в базе не должны ронять рассылку остальным."""
    user = await _person(session, at="вечером", tz="Nowhere/Special")
    assert reminders_service.due_date(user, datetime(2026, 8, 17, 18, 5, tzinfo=UTC)) is None


# --- кого включаем в рассылку ---


async def test_pending_lists_silent_user(session: AsyncSession):
    user = await _person(session)
    moment = datetime(2026, 8, 17, 18, 5, tzinfo=UTC)

    due = await reminders_service.pending(session, moment)
    assert [item.user.id for item in due] == [user.id]
    assert due[0].local_date == date(2026, 8, 17)


async def test_pending_skips_user_who_already_recorded(session: AsyncSession):
    user = await _person(session)
    # 09:30 по Москве того же дня
    await _spend(session, user, datetime(2026, 8, 17, 6, 30, tzinfo=UTC))

    due = await reminders_service.pending(session, datetime(2026, 8, 17, 18, 5, tzinfo=UTC))
    assert due == []


async def test_yesterday_entry_does_not_count(session: AsyncSession):
    """Траты за вчера сегодняшний день не закрывают — иначе напоминание бесполезно."""
    user = await _person(session)
    await _spend(session, user, datetime(2026, 8, 16, 18, 0, tzinfo=UTC))

    due = await reminders_service.pending(session, datetime(2026, 8, 17, 18, 5, tzinfo=UTC))
    assert [item.user.id for item in due] == [user.id]


async def test_entry_is_counted_in_the_users_own_day(session: AsyncSession):
    """Для новосибирца операция в 21:00 UTC — это уже следующее утро, а не сегодня."""
    user = await _person(session, tz=NSK)
    await _spend(session, user, datetime(2026, 8, 17, 21, 0, tzinfo=UTC))  # 18.08, 04:00 по НСК

    # 17.08, 21:05 по НСК — за 17-е у него по-прежнему пусто
    due = await reminders_service.pending(session, datetime(2026, 8, 17, 14, 5, tzinfo=UTC))
    assert [item.user.id for item in due] == [user.id]


async def test_other_persons_entry_does_not_help(session: AsyncSession):
    """Напоминание личное: записал один — второму всё равно напомним."""
    anya = await _person(session, 111, name="Аня")
    boris = await _person(session, 222, name="Боря")
    await _spend(session, anya, datetime(2026, 8, 17, 6, 30, tzinfo=UTC))

    due = await reminders_service.pending(session, datetime(2026, 8, 17, 18, 5, tzinfo=UTC))
    assert [item.user.id for item in due] == [boris.id]


async def test_stranger_is_not_reminded(session: AsyncSession):
    """Того, кого убрали из белого списка, беспокоить не за чем."""
    await _person(session, 333, name="Чужой")
    assert await reminders_service.pending(session, datetime(2026, 8, 17, 18, 5, tzinfo=UTC)) == []


async def test_mark_sent_closes_the_day(session: AsyncSession):
    user = await _person(session)
    moment = datetime(2026, 8, 17, 18, 5, tzinfo=UTC)

    due = await reminders_service.pending(session, moment)
    reminders_service.mark_sent(due[0])
    await session.flush()

    assert user.reminder_last_sent_on == date(2026, 8, 17)
    assert await reminders_service.pending(session, moment) == []


# --- доставка ---


class FakeBot:
    """Подменяет aiogram.Bot: запоминает отправленное, при желании падает.

    Настоящий бот в тестах не поднять, а проверять надо именно поведение вокруг
    отправки: отметку о доставке, повтор после сбоя и молчание при блокировке.
    """

    def __init__(self, fail: Exception | None = None) -> None:
        self.sent: list[int] = []
        self.fail = fail

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append(chat_id)


async def test_scheduler_runs_reminders_when_bot_is_up():
    """Задание должно попасть в планировщик, иначе всё остальное просто не запустится."""
    started = scheduler.start_scheduler(FakeBot())
    try:
        assert started is not None
        assert started.get_job("daily_reminders") is not None
    finally:
        scheduler.stop_scheduler()


async def test_scheduler_stays_idle_without_bot():
    """Ни Sheets, ни бота — поднимать планировщик не за чем."""
    assert scheduler.start_scheduler(None) is None


async def test_delivery_sends_once_per_day(session: AsyncSession):
    await _person(session)
    await session.commit()
    moment = datetime(2026, 8, 17, 18, 5, tzinfo=UTC)

    bot = FakeBot()
    assert await notify.send_due_reminders(bot, moment) == 1
    assert bot.sent == [111]

    # Второй тик той же минуты ничего не повторяет
    assert await notify.send_due_reminders(bot, moment) == 0
    assert bot.sent == [111]


async def test_network_failure_leaves_reminder_for_the_next_tick(session: AsyncSession):
    user = await _person(session)
    await session.commit()
    moment = datetime(2026, 8, 17, 18, 5, tzinfo=UTC)

    assert await notify.send_due_reminders(FakeBot(fail=TimeoutError("сеть")), moment) == 0
    await session.refresh(user)
    assert user.reminder_last_sent_on is None

    bot = FakeBot()
    assert await notify.send_due_reminders(bot, moment) == 1
    assert bot.sent == [111]


async def test_blocked_bot_is_not_retried_all_evening(session: AsyncSession):
    user = await _person(session)
    await session.commit()
    moment = datetime(2026, 8, 17, 18, 5, tzinfo=UTC)

    blocked = TelegramForbiddenError(method=None, message="bot was blocked by the user")
    assert await notify.send_due_reminders(FakeBot(fail=blocked), moment) == 0

    await session.refresh(user)
    assert user.reminder_last_sent_on == date(2026, 8, 17)


# --- API ---


async def test_default_settings_are_returned(auth_client: httpx.AsyncClient):
    body = (await auth_client.get("/api/me/reminder")).json()
    assert body["enabled"] is True
    assert body["time"] == "21:00"
    assert body["tz"]


async def test_time_and_switch_are_saved(auth_client: httpx.AsyncClient):
    saved = await auth_client.put(
        "/api/me/reminder", json={"time": "8:5", "tz": NSK, "enabled": True}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["time"] == "08:05"
    assert saved.json()["tz"] == NSK

    # Присылать можно любое подмножество полей — время при этом не теряется
    off = await auth_client.put("/api/me/reminder", json={"enabled": False})
    assert off.json() == {
        "enabled": False,
        "time": "08:05",
        "tz": NSK,
        "delivery_ready": False,  # в тестах BOT_MODE=off
    }


async def test_bad_settings_are_rejected(auth_client: httpx.AsyncClient):
    assert (await auth_client.put("/api/me/reminder", json={"time": "26:00"})).status_code == 400
    assert (
        await auth_client.put("/api/me/reminder", json={"tz": "Mars/Olympus"})
    ).status_code == 400

    # После отказа настройка осталась прежней
    assert (await auth_client.get("/api/me/reminder")).json()["time"] == "21:00"


async def test_login_remembers_browser_timezone(client: httpx.AsyncClient):
    """Пояс приезжает вместе с входом — иначе «21:00» считалось бы по серверному."""
    init_data = build_init_data(TOKEN, {"id": 111, "first_name": "Аня"})
    response = await client.post("/api/auth/login", json={"init_data": init_data, "tz": NSK})
    assert response.status_code == 200, response.text

    client.headers["Authorization"] = f"Bearer {response.json()['token']}"
    assert (await client.get("/api/me/reminder")).json()["tz"] == NSK


async def test_login_ignores_junk_timezone(client: httpx.AsyncClient):
    init_data = build_init_data(TOKEN, {"id": 111, "first_name": "Аня"})
    response = await client.post(
        "/api/auth/login", json={"init_data": init_data, "tz": "../../etc/passwd"}
    )
    assert response.status_code == 200, response.text

    client.headers["Authorization"] = f"Bearer {response.json()['token']}"
    # Осталась зона по умолчанию, мусор в базу не попал
    assert (await client.get("/api/me/reminder")).json()["tz"] == "Europe/Moscow"
