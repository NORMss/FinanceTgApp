"""Правка операций, уже попавших в журнал, и фильтры истории."""

import httpx

from app.security.initdata import build_init_data
from tests.conftest import USER_B

TOKEN = "123456:TEST-TOKEN"


async def _category(client: httpx.AsyncClient, name: str) -> dict:
    categories = (await client.get("/api/categories?kind=expense")).json()
    return next(item for item in categories if item["name"] == name)


async def test_shared_expense_with_two_people_is_listed(auth_client: httpx.AsyncClient):
    """Регрессия: с двумя участниками список операций отдавал 500.

    Трата с общего счёта делится пополам, и в ответе появляются доли. Схема SplitOut
    не умела читать ORM-объект, но заметить это на одном пользователе невозможно —
    доли тогда просто не создаются. Баг нашёлся на демо-данных, где участников двое.
    """
    await auth_client.post("/api/auth/login", json={"init_data": build_init_data(TOKEN, USER_B)})
    shared = (
        await auth_client.post("/api/accounts", json={"name": "Общий", "is_shared": True})
    ).json()

    created = await auth_client.post(
        "/api/transactions",
        json={"type": "expense", "amount": "1000", "account_id": shared["id"]},
    )
    assert created.status_code == 201, created.text
    assert len(created.json()["splits"]) == 2

    listing = await auth_client.get("/api/transactions?period=month")
    assert listing.status_code == 200, listing.text
    splits = listing.json()["items"][0]["splits"]
    assert sorted(item["share_minor"] for item in splits) == [50_000, 50_000]


async def test_moving_expense_off_the_shared_account_clears_the_debt(
    auth_client: httpx.AsyncClient,
):
    """Регрессия: правка счёта не пересчитывала доли, и долг оставался навсегда.

    Трата с общего счёта делится пополам и попадает во «Взаиморасчёты». Если потом
    выясняется, что платили со своей карты, счёт правят в истории — и на этом долг
    обязан исчезнуть. Раньше доли пересчитывались только при смене суммы или типа,
    поэтому «кто кому должен» показывал половину суммы уже несуществующей общей траты.
    """
    await auth_client.post("/api/auth/login", json={"init_data": build_init_data(TOKEN, USER_B)})
    shared = (
        await auth_client.post("/api/accounts", json={"name": "Общий", "is_shared": True})
    ).json()
    me = (await auth_client.get("/api/me")).json()
    mine = next(
        account
        for account in (await auth_client.get("/api/accounts")).json()
        if account["owner_id"] == me["id"] and not account["is_shared"]
    )

    created = (
        await auth_client.post(
            "/api/transactions",
            json={"type": "expense", "amount": "1000", "account_id": shared["id"]},
        )
    ).json()
    assert len(created["splits"]) == 2
    assert (await auth_client.get("/api/stats/settle")).json()["users"][0]["net_minor"] != 0

    moved = await auth_client.patch(
        f"/api/transactions/{created['id']}", json={"account_id": mine["id"]}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["splits"] == []

    settle = (await auth_client.get("/api/stats/settle")).json()
    assert [row["net_minor"] for row in settle["users"]] == [0, 0]
    assert [row["owed_minor"] for row in settle["users"]] == [0, 0]

    # И обратно: вернули на общий счёт — деление восстановилось
    back = await auth_client.patch(
        f"/api/transactions/{created['id']}", json={"account_id": shared["id"]}
    )
    assert sorted(item["share_minor"] for item in back.json()["splits"]) == [50_000, 50_000]


async def test_edits_every_field(auth_client: httpx.AsyncClient):
    food = await _category(auth_client, "Продукты")
    created = (
        await auth_client.post(
            "/api/transactions",
            json={"type": "expense", "amount": "100", "note": "черновик"},
        )
    ).json()

    updated = await auth_client.patch(
        f"/api/transactions/{created['id']}",
        json={
            "amount": "250,50",
            "category_id": food["id"],
            "note": "уточнил",
            "tags": "проверка",
            "occurred_at": "2026-08-01T10:00:00Z",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["amount_minor"] == 25_050
    assert body["category_id"] == food["id"]
    assert body["note"] == "уточнил"
    assert body["tags"] == "проверка"
    assert body["occurred_at"].startswith("2026-08-01")


async def test_category_can_be_cleared_but_not_by_accident(auth_client: httpx.AsyncClient):
    food = await _category(auth_client, "Продукты")
    created = (
        await auth_client.post(
            "/api/transactions",
            json={"type": "expense", "amount": "100", "category_id": food["id"]},
        )
    ).json()

    # Ключа в запросе нет — категория остаётся на месте
    kept = await auth_client.patch(f"/api/transactions/{created['id']}", json={"note": "и всё"})
    assert kept.json()["category_id"] == food["id"]

    # Явный null — снимаем категорию
    cleared = await auth_client.patch(
        f"/api/transactions/{created['id']}", json={"category_id": None}
    )
    assert cleared.json()["category_id"] is None


async def test_type_can_be_switched(auth_client: httpx.AsyncClient):
    created = (
        await auth_client.post("/api/transactions", json={"type": "expense", "amount": "700"})
    ).json()

    updated = await auth_client.patch(
        f"/api/transactions/{created['id']}", json={"type": "income"}
    )
    assert updated.json()["type"] == "income"

    summary = (await auth_client.get("/api/stats/summary?period=month")).json()
    assert summary["income_minor"] == 70_000
    assert summary["expense_minor"] == 0


async def test_edit_rejects_bad_values(auth_client: httpx.AsyncClient):
    created = (
        await auth_client.post("/api/transactions", json={"type": "expense", "amount": "10"})
    ).json()

    assert (
        await auth_client.patch(f"/api/transactions/{created['id']}", json={"amount": "-5"})
    ).status_code == 400
    assert (
        await auth_client.patch("/api/transactions/несуществующая", json={"amount": "5"})
    ).status_code == 404


async def test_subcategory_totals_roll_up_into_parent(auth_client: httpx.AsyncClient):
    parent = await _category(auth_client, "Продукты")
    child = (
        await auth_client.post(
            "/api/categories", json={"name": "Азбука вкуса", "parent_id": parent["id"]}
        )
    ).json()

    await auth_client.post(
        "/api/transactions",
        json={"type": "expense", "amount": "300", "category_id": child["id"]},
    )
    await auth_client.post(
        "/api/transactions",
        json={"type": "expense", "amount": "200", "category_id": parent["id"]},
    )

    rows = (await auth_client.get("/api/stats/summary?period=month")).json()["by_category"]
    parent_row = next(row for row in rows if row["category_id"] == parent["id"])
    child_row = next(row for row in rows if row["category_id"] == child["id"])

    # Родитель показывает всё вместе, own_minor — только то, что записано на него самого
    assert parent_row["amount_minor"] == 50_000
    assert parent_row["own_minor"] == 20_000
    assert child_row["amount_minor"] == 30_000
    assert child_row["parent_id"] == parent["id"]
    # Подкатегория идёт сразу за родителем: клиенту остаётся сделать отступ
    assert rows.index(child_row) == rows.index(parent_row) + 1


async def test_filter_by_parent_category_includes_children(auth_client: httpx.AsyncClient):
    parent = await _category(auth_client, "Продукты")
    child = (
        await auth_client.post(
            "/api/categories", json={"name": "Дикси", "parent_id": parent["id"]}
        )
    ).json()
    await auth_client.post(
        "/api/transactions",
        json={"type": "expense", "amount": "300", "category_id": child["id"]},
    )
    await auth_client.post("/api/transactions", json={"type": "expense", "amount": "999"})

    listing = (
        await auth_client.get(f"/api/transactions?period=month&category_ids={parent['id']}")
    ).json()
    assert listing["total"] == 1
    assert listing["items"][0]["amount_minor"] == 30_000


async def test_filter_by_author(auth_client: httpx.AsyncClient):
    me = (await auth_client.get("/api/me")).json()
    await auth_client.post("/api/transactions", json={"type": "expense", "amount": "150"})

    mine = (
        await auth_client.get(f"/api/stats/summary?period=month&author_ids={me['id']}")
    ).json()
    assert mine["expense_minor"] == 15_000

    stranger = (
        await auth_client.get("/api/stats/summary?period=month&author_ids=не-я")
    ).json()
    assert stranger["expense_minor"] == 0
