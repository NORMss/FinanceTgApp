"""Проверка подлинности initData из Telegram Mini App.

Алгоритм по документации Telegram:
  1. Разобрать initData как query string.
  2. Собрать data-check-string: все пары КРОМЕ `hash`, отсортированные по ключу,
     склеенные через \\n в формате `key=value`.
  3. secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
  4. Ожидаемый хеш = HMAC_SHA256(key=secret_key, msg=data_check_string) в hex.
  5. Сравнить с присланным `hash` в constant time.

Из строки исключается ровно одно поле — `hash`. Поле `signature` (отдельная Ed25519-подпись
для сторонних сервисов, которым нельзя показывать токен бота) выкидывать нельзя: Telegram
считает `hash` по всем остальным полям, включая его. Если убрать `signature`, подпись не
сойдётся на любом клиенте, который это поле присылает.

Дополнительно проверяем `auth_date`: без этого украденная строка initData работает вечно.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from urllib.parse import parse_qsl

from app.util.dates import now


class InitDataError(ValueError):
    """initData не прошла проверку. Наружу отдаём 401 без подробностей."""


@dataclass(frozen=True, slots=True)
class TelegramUser:
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str | None = None
    language_code: str | None = None
    is_premium: bool = False

    @property
    def display_name(self) -> str:
        full = " ".join(part for part in (self.first_name, self.last_name) if part).strip()
        return full or self.username or f"id{self.id}"


def parse_init_data(init_data: str) -> dict[str, str]:
    if not init_data:
        raise InitDataError("пустая initData")
    return dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))


def validate_init_data(
    init_data: str, bot_token: str, max_age_seconds: int = 86400
) -> TelegramUser:
    if not bot_token:
        raise InitDataError("BOT_TOKEN не сконфигурирован")

    fields = parse_init_data(init_data)
    received_hash = fields.pop("hash", "")
    if not received_hash:
        raise InitDataError("в initData нет hash")

    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        raise InitDataError("подпись initData не совпала")

    auth_date = fields.get("auth_date")
    if not auth_date or not auth_date.isdigit():
        raise InitDataError("в initData нет auth_date")
    age = int(now().timestamp()) - int(auth_date)
    if age > max_age_seconds:
        raise InitDataError("initData устарела")

    raw_user = fields.get("user")
    if not raw_user:
        raise InitDataError("в initData нет user")
    try:
        payload = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise InitDataError("user в initData не разобрался") from exc

    return TelegramUser(
        id=int(payload["id"]),
        first_name=payload.get("first_name", ""),
        last_name=payload.get("last_name", ""),
        username=payload.get("username"),
        language_code=payload.get("language_code"),
        is_premium=bool(payload.get("is_premium", False)),
    )


def build_init_data(
    bot_token: str,
    user: dict,
    auth_date: int | None = None,
    extra: dict[str, str] | None = None,
) -> str:
    """Собирает валидную initData. Нужна только тестам — в проде её делает Telegram.

    `extra` позволяет добавить поля, которые присылают реальные клиенты (`signature`,
    `query_id`, `chat_instance`), и убедиться, что они не ломают проверку.
    """
    from urllib.parse import urlencode

    fields = {
        "auth_date": str(auth_date or int(now().timestamp())),
        "user": json.dumps(user, separators=(",", ":"), ensure_ascii=False),
        **(extra or {}),
    }
    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)
