"""Дерево категорий: создание, правка, перенос, удаление.

Проверяем ровно те правила, ради которых написан services/catalog: без них справочник
за месяц зарастает дублями и трёхуровневыми ветками, которые некуда показать.
"""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CategoryKind
from app.repositories import categories as categories_repo
from app.services import catalog


async def _root(session: AsyncSession, name: str = "Супермаркет"):
    return await catalog.create_category(session, name=name, icon="🛒")


async def test_creates_two_level_tree(seeded: AsyncSession):
    parent = await _root(seeded)
    child = await catalog.create_category(
        seeded, name="Пятёрочка", icon="🟢", parent_id=parent.id
    )

    assert child.parent_id == parent.id
    assert child.kind == parent.kind
    assert catalog.full_name(child, {parent.id: parent}) == "Супермаркет · Пятёрочка"


async def test_third_level_is_rejected(seeded: AsyncSession):
    parent = await _root(seeded)
    child = await catalog.create_category(seeded, name="Пятёрочка", parent_id=parent.id)

    with pytest.raises(catalog.CatalogError):
        await catalog.create_category(seeded, name="Касса №3", parent_id=child.id)


async def test_subcategory_kind_must_match_parent(seeded: AsyncSession):
    parent = await _root(seeded)
    with pytest.raises(catalog.CatalogError):
        await catalog.create_category(
            seeded, name="Премия", kind=CategoryKind.INCOME, parent_id=parent.id
        )


async def test_duplicate_names_are_rejected_per_level(seeded: AsyncSession):
    parent = await _root(seeded)
    await catalog.create_category(seeded, name="Пятёрочка", parent_id=parent.id)

    with pytest.raises(catalog.CatalogError):
        await catalog.create_category(seeded, name="пятёрочка", parent_id=parent.id)

    # Под другим родителем то же имя допустимо: «Доставка» бывает и у еды, и у маркетплейсов
    other = await _root(seeded, "Маркетплейсы")
    await catalog.create_category(seeded, name="Пятёрочка", parent_id=other.id)


async def test_category_cannot_become_its_own_parent(seeded: AsyncSession):
    parent = await _root(seeded)
    with pytest.raises(catalog.CatalogError):
        await catalog.update_category(seeded, parent, parent_id=parent.id)


async def test_parent_with_children_cannot_be_nested(seeded: AsyncSession):
    parent = await _root(seeded)
    await catalog.create_category(seeded, name="Пятёрочка", parent_id=parent.id)
    other = await _root(seeded, "Еда")

    with pytest.raises(catalog.CatalogError):
        await catalog.update_category(seeded, parent, parent_id=other.id)


async def test_hiding_parent_hides_children(seeded: AsyncSession):
    parent = await _root(seeded)
    child = await catalog.create_category(seeded, name="Пятёрочка", parent_id=parent.id)

    await catalog.update_category(seeded, parent, archived=True)
    assert child.archived is True


async def test_unused_category_is_deleted_outright(seeded: AsyncSession):
    unused = await _root(seeded, "Ненужная")
    assert await catalog.delete_category(seeded, unused) == "deleted"
    assert await categories_repo.get(seeded, unused.id) is None


async def test_used_category_survives_deletion(auth_client: httpx.AsyncClient):
    created = (
        await auth_client.post("/api/categories", json={"name": "Кальян", "icon": "💨"})
    ).json()
    await auth_client.post(
        "/api/transactions", json={"type": "expense", "amount": "100", "category_id": created["id"]}
    )

    response = await auth_client.delete(f"/api/categories/{created['id']}")
    assert response.status_code == 200
    # Категорию с операциями стирать нельзя: журнал за прошлый месяц потерял бы разбивку
    assert response.json()["result"] == "archived"

    visible = (await auth_client.get("/api/categories")).json()
    assert all(item["id"] != created["id"] for item in visible)


async def test_icon_accepts_emoji_and_text(seeded: AsyncSession):
    assert catalog.clean_icon("🛒") == "🛒"
    assert catalog.clean_icon(" КБ ") == "КБ"
    assert catalog.clean_icon("👨‍👩‍👧") == "👨‍👩‍👧"  # ZWJ-склейка не должна распадаться
    assert catalog.clean_icon("а\nб") == "аб"
    with pytest.raises(catalog.CatalogError):
        catalog.clean_icon("слишком длинная строка вместо значка")


async def test_api_creates_and_edits_subcategory(auth_client: httpx.AsyncClient):
    categories = (await auth_client.get("/api/categories?kind=expense")).json()
    parent = next(item for item in categories if item["name"] == "Продукты")

    created = await auth_client.post(
        "/api/categories",
        json={"name": "Ашан", "icon": "🅰️", "parent_id": parent["id"]},
    )
    assert created.status_code == 201, created.text
    child_id = created.json()["id"]

    renamed = await auth_client.patch(
        f"/api/categories/{child_id}", json={"name": "Ашан Сити", "icon": "🏬"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Ашан Сити"
    assert renamed.json()["icon"] == "🏬"

    # null в parent_id — это команда «поднять на верхний уровень»
    lifted = await auth_client.patch(f"/api/categories/{child_id}", json={"parent_id": None})
    assert lifted.json()["parent_id"] is None


async def test_api_rejects_bad_category(auth_client: httpx.AsyncClient):
    # Пустое имя отсекает pydantic, из одних пробелов — уже правило справочника
    assert (await auth_client.post("/api/categories", json={"name": ""})).status_code == 422
    assert (await auth_client.post("/api/categories", json={"name": "  "})).status_code == 400
    duplicate = await auth_client.post("/api/categories", json={"name": "Продукты"})
    assert duplicate.status_code == 400
