"""Что приложение рассказывает о себе постороннему.

Смысл этих проверок — не «работает ли функция», а «сколько лишнего утекает наружу».
Ошибки должны быть одинаковыми и скучными, схемы API — закрытыми, попытки входа —
ограниченными по частоте.
"""

import httpx
import pytest

from app.config import settings
from app.security.initdata import build_init_data
from app.security.ratelimit import RateLimiter

TOKEN = "123456:TEST-TOKEN"


async def test_login_failures_look_identical(client: httpx.AsyncClient):
    """Испорченная подпись и чужой telegram_id не должны различаться по тексту.

    Иначе по ответу видно, дошёл ли перебор до проверки белого списка, — а это
    подсказка, что подпись подобрана верно.
    """
    broken = await client.post("/api/auth/login", json={"init_data": "hash=bad"})
    stranger = await client.post(
        "/api/auth/login",
        json={"init_data": build_init_data(TOKEN, {"id": 999, "first_name": "Чужой"})},
    )

    assert broken.json()["detail"] == stranger.json()["detail"] == "Не удалось войти"
    assert "initData" not in broken.text
    assert "999" not in stranger.text


async def test_token_errors_say_nothing(client: httpx.AsyncClient):
    for header in ("", "Bearer", "Bearer not-a-real-token", "Basic dXNlcjpwYXNz"):
        response = await client.get(
            "/api/transactions", headers={"Authorization": header} if header else {}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Нет доступа"


async def test_api_schema_is_closed(client: httpx.AsyncClient):
    assert settings.enable_docs is False
    assert (await client.get("/api/openapi.json")).status_code == 404
    assert (await client.get("/api/docs")).status_code == 404


async def test_unknown_api_paths_answer_the_same(client: httpx.AsyncClient):
    """Несуществующая ручка и существующая-но-закрытая не должны различаться настолько,
    чтобы по ним можно было составить карту API."""
    for path in ("/api/admin", "/api/users/all", "/api/.env", "/api/v2/transactions"):
        response = await client.get(path)
        assert response.status_code == 404
        assert response.json()["detail"] == "Не найдено"


async def test_security_headers_are_set(client: httpx.AsyncClient):
    headers = (await client.get("/api/health")).headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"
    assert "noindex" in headers["x-robots-tag"]
    csp = headers["content-security-policy"]
    # Вставить Mini App во фрейм можно только из Telegram — это защита от кликджекинга
    assert "frame-ancestors https://web.telegram.org https://telegram.org" in csp
    assert "object-src 'none'" in csp


async def test_robots_forbids_indexing(client: httpx.AsyncClient):
    response = await client.get("/robots.txt")
    assert "Disallow: /" in response.text


async def test_webhook_without_secret_is_invisible(client: httpx.AsyncClient):
    """Неверный секрет вебхука получает 404, а не 403: 403 подтверждает, что адрес угадан."""
    if not settings.webhook_secret:
        pytest.skip("секрет вебхука в тестовой конфигурации не задан")
    response = await client.post(
        settings.webhook_path, json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"}
    )
    assert response.status_code == 404
    # Пустой секрет тоже не проходит
    assert (await client.post(settings.webhook_path, json={})).status_code == 404


def test_rate_limiter_blocks_after_limit():
    limiter = RateLimiter(limit=3, window_seconds=60)
    for _ in range(3):
        assert limiter.is_blocked("1.2.3.4") is False
        limiter.register_failure("1.2.3.4")

    assert limiter.is_blocked("1.2.3.4") is True
    assert limiter.retry_after("1.2.3.4") > 0
    # Соседний адрес не страдает от чужих попыток
    assert limiter.is_blocked("5.6.7.8") is False
    # Удачный вход обнуляет историю
    limiter.reset("1.2.3.4")
    assert limiter.is_blocked("1.2.3.4") is False


def test_rate_limiter_does_not_grow_without_bound():
    limiter = RateLimiter(limit=1, window_seconds=60)
    for index in range(5000):
        limiter.register_failure(f"10.0.{index // 256}.{index % 256}")
    assert len(limiter._clients) <= 2048  # noqa: SLF001 — проверяем именно внутреннее состояние


async def test_login_is_rate_limited(client: httpx.AsyncClient):
    """После серии неудач вход отвечает 429 — перебор подписи становится бессмысленным."""
    from app.api.routes import auth as auth_route

    auth_route._limiter = RateLimiter(limit=3, window_seconds=300)  # noqa: SLF001
    try:
        for _ in range(3):
            assert (
                await client.post("/api/auth/login", json={"init_data": "hash=bad"})
            ).status_code == 401

        blocked = await client.post("/api/auth/login", json={"init_data": "hash=bad"})
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"].isdigit()
        assert blocked.json()["detail"] == "Не удалось войти"
    finally:
        auth_route._limiter = RateLimiter(  # noqa: SLF001
            settings.login_attempts, settings.login_window_seconds
        )
