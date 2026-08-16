"""Счета: что стоит по умолчанию и когда появляется общий кошелёк.

Умолчанием был общий счёт, и это оказалось неверным решением: каждая трата с него
делится пополам и создаёт долг второму участнику. Пользователь при этом ничего
не выбирал — просто ввёл сумму. Теперь по умолчанию деньги списываются со своего
счёта, а общий заводят руками, когда он действительно есть.
"""

import httpx

from app.security.initdata import build_init_data
from tests.conftest import USER_B

TOKEN = "123456:TEST-TOKEN"


async def _accounts(client: httpx.AsyncClient) -> list[dict]:
    return (await client.get("/api/accounts")).json()


async def test_fresh_install_has_no_shared_account(auth_client: httpx.AsyncClient):
    accounts = await _accounts(auth_client)
    assert [account["is_shared"] for account in accounts] == [False]


async def test_entry_without_account_lands_on_my_own(auth_client: httpx.AsyncClient):
    me = (await auth_client.get("/api/me")).json()
    mine = (await _accounts(auth_client))[0]

    created = (
        await auth_client.post("/api/transactions", json={"type": "expense", "amount": "500"})
    ).json()

    assert created["account_id"] == mine["id"]
    assert mine["owner_id"] == me["id"]
    # Личная трата не делится, и во «Взаиморасчётах» после неё пусто
    assert created["splits"] == []
    settle = (await auth_client.get("/api/stats/settle")).json()
    assert all(row["net_minor"] == 0 for row in settle["users"])


async def test_shared_account_does_not_steal_the_default(auth_client: httpx.AsyncClient):
    """Даже когда общий счёт заведён, умолчание остаётся личным."""
    await auth_client.post("/api/auth/login", json={"init_data": build_init_data(TOKEN, USER_B)})
    await auth_client.post("/api/accounts", json={"name": "Общий счёт", "is_shared": True})
    me = (await auth_client.get("/api/me")).json()

    created = (
        await auth_client.post("/api/transactions", json={"type": "expense", "amount": "500"})
    ).json()

    mine = next(
        account
        for account in await _accounts(auth_client)
        if account["owner_id"] == me["id"] and not account["is_shared"]
    )
    assert created["account_id"] == mine["id"]
    assert created["splits"] == []


async def test_second_shared_account_is_refused(auth_client: httpx.AsyncClient):
    first = await auth_client.post("/api/accounts", json={"name": "Общий", "is_shared": True})
    assert first.status_code == 201, first.text

    second = await auth_client.post("/api/accounts", json={"name": "Ещё общий", "is_shared": True})
    assert second.status_code == 400

    # Личных счетов можно завести сколько угодно — ограничение только на общий
    extra = await auth_client.post("/api/accounts", json={"name": "Копилка"})
    assert extra.status_code == 201
