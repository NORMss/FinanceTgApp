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
