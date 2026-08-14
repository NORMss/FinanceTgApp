"""Проверки разбора конфигурации.

Ошибки здесь стоят дороже всего: приложение стартует, выглядит рабочим, а Mini App
получает 401 — и причину видно только по подписи, которая не сходится.
"""

import pytest

from app.config import Settings

TOKEN = "123456:AA-Test_Token"


def _settings(**kwargs) -> Settings:
    # _env_file=None отключает чтение .env: тест не должен зависеть от машины
    return Settings(_env_file=None, **kwargs)


@pytest.mark.parametrize(
    "raw",
    [
        TOKEN,
        f"{TOKEN}\r",  # .env сохранён с переводами строк Windows
        f"{TOKEN}\n",
        f"  {TOKEN}  ",  # пробелы от копипасты
        f'"{TOKEN}"',  # кавычки, как в shell-скриптах
        f"'{TOKEN}'",
    ],
)
def test_bot_token_is_cleaned(raw):
    assert _settings(bot_token=raw).bot_token == TOKEN


def test_bot_id_extracted_from_token():
    assert _settings(bot_token=TOKEN).bot_id == 123456
    assert _settings(bot_token="мусор").bot_id is None


def test_allowed_ids_parsed_from_csv():
    settings = _settings(allowed_telegram_ids=" 111, 222 ,333")
    assert settings.allowed_ids == frozenset({111, 222, 333})
    assert settings.is_allowed(222)
    assert not settings.is_allowed(444)


def test_empty_whitelist_lets_nobody_in():
    """Пустой список — это «никого», а не «всех»: защита от деплоя нараспашку."""
    assert not _settings(allowed_telegram_ids="").is_allowed(111)
