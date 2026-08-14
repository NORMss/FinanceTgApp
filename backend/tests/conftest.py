"""Общая обвязка тестов.

Переменные окружения выставляются до импорта приложения: настройки читаются один раз
и кэшируются, поэтому подменять их после импорта уже поздно.
"""

import os
import tempfile
from pathlib import Path

import pytest

_TMP_DB = Path(tempfile.mkdtemp(prefix="financetg-tests-")) / "test.db"

os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{_TMP_DB}",
        "BOT_TOKEN": "123456:TEST-TOKEN",
        "ALLOWED_TELEGRAM_IDS": "111,222",
        "JWT_SECRET": "test-secret-value-for-tests-only",
        "BOT_MODE": "off",
        "SHEETS_ENABLED": "false",
        "DEV_AUTH_BYPASS": "false",
        "PUBLIC_URL": "https://example.test",
        "WEBHOOK_SECRET": "test-webhook-secret",
    }
)

import httpx  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db import get_engine, get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.security.initdata import build_init_data  # noqa: E402
from app.services import bootstrap  # noqa: E402

USER_A = {"id": 111, "first_name": "Аня"}
USER_B = {"id": 222, "first_name": "Боря"}


@pytest.fixture(autouse=True)
async def fresh_schema():
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def session() -> AsyncSession:
    async with get_session_factory()() as db_session:
        yield db_session
        await db_session.commit()


@pytest.fixture
async def seeded(session: AsyncSession) -> AsyncSession:
    await bootstrap.ensure_reference_data(session)
    await session.commit()
    return session


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
async def auth_client(client: httpx.AsyncClient):
    """Клиент с токеном пользователя A."""
    init_data = build_init_data("123456:TEST-TOKEN", USER_A)
    response = await client.post("/api/auth/login", json={"init_data": init_data})
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['token']}"
    return client
