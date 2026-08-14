import time

import pytest

from app.security.initdata import InitDataError, build_init_data, validate_init_data

TOKEN = "123456:TEST-TOKEN"
USER = {"id": 111, "first_name": "Аня", "username": "anya"}


def test_valid_init_data_passes():
    user = validate_init_data(build_init_data(TOKEN, USER), TOKEN)
    assert user.id == 111
    assert user.display_name == "Аня"


def test_tampered_payload_is_rejected():
    init_data = build_init_data(TOKEN, USER).replace("111", "999")
    with pytest.raises(InitDataError):
        validate_init_data(init_data, TOKEN)


def test_wrong_bot_token_is_rejected():
    with pytest.raises(InitDataError):
        validate_init_data(build_init_data(TOKEN, USER), "999999:OTHER")


def test_stale_init_data_is_rejected():
    old = build_init_data(TOKEN, USER, auth_date=int(time.time()) - 100_000)
    with pytest.raises(InitDataError):
        validate_init_data(old, TOKEN, max_age_seconds=3600)


def test_empty_init_data_is_rejected():
    with pytest.raises(InitDataError):
        validate_init_data("", TOKEN)


def test_signature_field_does_not_break_validation():
    """Регрессия: `signature` обязан участвовать в подсчёте hash.

    Telegram присылает это поле современным клиентам и считает `hash` по всем полям,
    кроме самого `hash`. Пока мы выкидывали `signature`, вход давал 401 на живом
    Telegram, хотя все тесты с искусственной initData проходили.
    """
    init_data = build_init_data(
        TOKEN,
        USER,
        extra={
            "signature": "abcDEF123_-",
            "query_id": "AAH123",
            "chat_instance": "-1234567890",
        },
    )
    assert validate_init_data(init_data, TOKEN).id == 111


def test_matches_aiogram_reference_implementation():
    """Сверяемся с реализацией aiogram: расхождение здесь означает, что мы
    разошлись с документацией Telegram, и вход сломается на проде."""
    from aiogram.utils.web_app import check_webapp_signature

    init_data = build_init_data(TOKEN, USER, extra={"signature": "xyz"})
    assert check_webapp_signature(TOKEN, init_data) is True
    assert validate_init_data(init_data, TOKEN).id == 111

    tampered = init_data.replace("111", "222")
    assert check_webapp_signature(TOKEN, tampered) is False
    with pytest.raises(InitDataError):
        validate_init_data(tampered, TOKEN)
