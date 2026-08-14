from functools import cached_property, lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация приложения. Читается из переменных окружения и .env в корне репозитория."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram ---
    bot_token: str = ""
    public_url: str = "http://localhost:5173"
    # Строкой, а не list[int]: pydantic-settings пытается разобрать сложные типы как JSON,
    # и «111,222» из .env до валидатора просто не доезжает
    allowed_telegram_ids: str = ""
    bot_mode: Literal["webhook", "polling", "off"] = "polling"
    webhook_secret: str = ""
    webhook_path: str = "/tg/webhook"

    # --- Приложение ---
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_seconds: int = 60 * 60 * 24 * 7
    # Максимальный возраст initData, после которого требуем свежий запуск Mini App
    init_data_max_age_seconds: int = 60 * 60 * 24
    base_currency: str = "RUB"
    log_level: str = "INFO"
    dev_auth_bypass: bool = False
    dev_telegram_id: int = 0

    # --- Защита ---
    # Подробности отказа в доступе. Выключено: чужому человеку незачем знать, дело
    # в белом списке, в подписи или в часах на сервере. Причина всегда пишется в лог,
    # так что для отладки достаточно `docker compose logs app`.
    debug_errors: bool = False
    # Swagger и схема API. В приватном приложении это карта всех ручек для того,
    # кто нашёл адрес, — по умолчанию закрыто.
    enable_docs: bool = False
    # Сколько неудачных входов с одного адреса терпим и за какое время
    login_attempts: int = 10
    login_window_seconds: int = 300
    # Брать адрес клиента из X-Forwarded-For. Верно, когда снаружи стоит наш прокси,
    # и опасно, если приложение смотрит в интернет напрямую: заголовок легко подделать
    trust_proxy_header: bool = True

    # Каталог со сборкой Mini App. Если задан, приложение отдаёт статику само —
    # это нужно, когда снаружи уже стоит чужой nginx/Caddy и свой поднимать некуда.
    static_dir: Path | None = None

    # --- База ---
    database_url: str = "sqlite+aiosqlite:///./data/app.db"

    # --- Google Sheets ---
    sheets_enabled: bool = False
    google_credentials_file: Path = Path("./data/google-credentials.json")
    google_spreadsheet_id: str = ""
    sheets_sync_interval: int = 60

    @field_validator("bot_token", "webhook_secret", "jwt_secret", mode="before")
    @classmethod
    def _strip_secret(cls, value: object) -> object:
        """Срезает невидимый мусор вокруг секретов.

        Файл .env, сохранённый с переводами строк Windows, даёт токену хвост `\\r`,
        а копипаста — пробел или кавычки. Токен при этом выглядит правильным, но HMAC
        считается от другой строки, и Mini App получает 401 с «подпись не совпала».
        """
        if isinstance(value, str):
            return value.strip().strip("\"'").strip()
        return value

    @property
    def bot_id(self) -> int | None:
        """Числовая часть токена до двоеточия — это id бота, не секрет."""
        head = self.bot_token.split(":", 1)[0]
        return int(head) if head.isdigit() else None

    @cached_property
    def allowed_ids(self) -> frozenset[int]:
        parts = (part.strip() for part in self.allowed_telegram_ids.split(","))
        return frozenset(int(part) for part in parts if part.lstrip("-").isdigit())

    @property
    def webhook_url(self) -> str:
        return f"{self.public_url.rstrip('/')}{self.webhook_path}"

    @property
    def sheets_ready(self) -> bool:
        return bool(
            self.sheets_enabled
            and self.google_spreadsheet_id
            and self.google_credentials_file.exists()
        )

    def is_allowed(self, telegram_id: int) -> bool:
        """Приложение приватное: пускаем только явно перечисленных пользователей.

        Пустой список означает «никого» — это защита от случайного деплоя нараспашку.
        """
        return telegram_id in self.allowed_ids


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
