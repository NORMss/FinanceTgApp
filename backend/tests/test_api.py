import httpx

from app.security.initdata import build_init_data
from tests.conftest import USER_A

TOKEN = "123456:TEST-TOKEN"


async def test_health(client: httpx.AsyncClient):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_login_requires_valid_init_data(client: httpx.AsyncClient):
    assert (await client.post("/api/auth/login", json={"init_data": "hash=bad"})).status_code == 401


async def test_stranger_is_rejected(client: httpx.AsyncClient):
    """Пользователь не из ALLOWED_TELEGRAM_IDS не должен попасть внутрь."""
    init_data = build_init_data(TOKEN, {"id": 999, "first_name": "Чужой"})
    response = await client.post("/api/auth/login", json={"init_data": init_data})
    assert response.status_code == 403


async def test_endpoints_require_token(client: httpx.AsyncClient):
    assert (await client.get("/api/transactions")).status_code == 401


async def test_login_creates_user_and_defaults(auth_client: httpx.AsyncClient):
    me = await auth_client.get("/api/me")
    assert me.json()["telegram_id"] == USER_A["id"]

    accounts = (await auth_client.get("/api/accounts")).json()
    assert any(account["is_shared"] for account in accounts)

    categories = (await auth_client.get("/api/categories")).json()
    assert any(category["name"] == "Продукты" for category in categories)


async def test_create_and_list_transaction(auth_client: httpx.AsyncClient):
    categories = (await auth_client.get("/api/categories?kind=expense")).json()
    food = next(item for item in categories if item["name"] == "Продукты")

    created = await auth_client.post(
        "/api/transactions",
        json={"type": "expense", "amount": "1 234,56", "category_id": food["id"], "note": "тест"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["amount_minor"] == 123456

    listing = (await auth_client.get("/api/transactions?period=month")).json()
    assert listing["total"] == 1
    assert listing["items"][0]["note"] == "тест"


async def test_summary_reflects_transactions(auth_client: httpx.AsyncClient):
    await auth_client.post("/api/transactions", json={"type": "expense", "amount": "100"})
    await auth_client.post("/api/transactions", json={"type": "income", "amount": "250"})

    summary = (await auth_client.get("/api/stats/summary?period=month")).json()
    assert summary["expense_minor"] == 10_000
    assert summary["income_minor"] == 25_000
    assert summary["net_minor"] == 15_000


async def test_delete_removes_from_list(auth_client: httpx.AsyncClient):
    created = (
        await auth_client.post("/api/transactions", json={"type": "expense", "amount": "10"})
    ).json()

    assert (await auth_client.delete(f"/api/transactions/{created['id']}")).status_code == 204
    listing = (await auth_client.get("/api/transactions?period=month")).json()
    assert listing["total"] == 0


async def test_bad_amount_is_rejected(auth_client: httpx.AsyncClient):
    response = await auth_client.post(
        "/api/transactions", json={"type": "expense", "amount": "не число"}
    )
    assert response.status_code == 400


async def test_balances_and_settle(auth_client: httpx.AsyncClient):
    await auth_client.post("/api/transactions", json={"type": "income", "amount": "1000"})

    balances = (await auth_client.get("/api/stats/balances")).json()
    assert balances["total_minor"] == 100_000

    settle = (await auth_client.get("/api/stats/settle")).json()
    assert "hint" in settle


async def test_llm_export_is_markdown(auth_client: httpx.AsyncClient):
    await auth_client.post("/api/transactions", json={"type": "expense", "amount": "500"})
    response = await auth_client.get("/api/export/llm?period=year")
    assert response.status_code == 200
    assert "Дамп расходов" in response.text


async def test_sync_status_reports_disabled(auth_client: httpx.AsyncClient):
    status = (await auth_client.get("/api/sync/status")).json()
    assert status["enabled"] is False
    assert status["configured"] is False
