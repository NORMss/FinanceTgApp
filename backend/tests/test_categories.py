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
    result = await catalog.delete_category(seeded, unused)
    assert result == {"result": "deleted", "moved": 0, "removed": 1}
    assert await categories_repo.get(seeded, unused.id) is None


async def test_used_category_needs_a_replacement(auth_client: httpx.AsyncClient):
    """Операции не должны остаться без категории — иначе отчёт за прошлый месяц врёт."""
    created = (
        await auth_client.post("/api/categories", json={"name": "Кальян", "icon": "💨"})
    ).json()
    await auth_client.post(
        "/api/transactions", json={"type": "expense", "amount": "100", "category_id": created["id"]}
    )

    refused = await auth_client.delete(f"/api/categories/{created['id']}")
    assert refused.status_code == 409, refused.text

    usage = (await auth_client.get(f"/api/categories/{created['id']}/usage")).json()
    assert usage == {"transactions": 1, "children": 0, "rules": 0, "needs_replacement": True}

    # Категория на месте: отказ ничего не поломал
    assert any(
        item["id"] == created["id"] for item in (await auth_client.get("/api/categories")).json()
    )


async def test_deletion_moves_transactions_to_the_replacement(auth_client: httpx.AsyncClient):
    doomed = (await auth_client.post("/api/categories", json={"name": "Кальян"})).json()
    keeper = (await auth_client.post("/api/categories", json={"name": "Привычки"})).json()
    tx = (
        await auth_client.post(
            "/api/transactions",
            json={"type": "expense", "amount": "700", "category_id": doomed["id"]},
        )
    ).json()

    deleted = await auth_client.delete(
        f"/api/categories/{doomed['id']}?move_to={keeper['id']}"
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"result": "deleted", "moved": 1, "removed": 1}

    # Операция цела и теперь считается в категории-замене
    assert (await auth_client.get(f"/api/transactions/{tx['id']}")).json()["category_id"] == (
        keeper["id"]
    )
    rows = (await auth_client.get("/api/stats/summary?period=month")).json()["by_category"]
    assert next(row for row in rows if row["category_id"] == keeper["id"])["amount_minor"] == 70_000
    assert all(row["category_id"] != doomed["id"] for row in rows)


async def test_deletion_takes_subcategories_with_it(auth_client: httpx.AsyncClient):
    """Удаляем корень — вместе с ним уходят дети, а их операции переезжают в замену."""
    parent = (await auth_client.post("/api/categories", json={"name": "Супермаркет"})).json()
    child = (
        await auth_client.post(
            "/api/categories", json={"name": "Пятёрочка", "parent_id": parent["id"]}
        )
    ).json()
    keeper = (await auth_client.post("/api/categories", json={"name": "Еда"})).json()

    for category_id in (parent["id"], child["id"]):
        await auth_client.post(
            "/api/transactions",
            json={"type": "expense", "amount": "100", "category_id": category_id},
        )

    usage = (await auth_client.get(f"/api/categories/{parent['id']}/usage")).json()
    assert usage["transactions"] == 2
    assert usage["children"] == 1

    deleted = await auth_client.delete(f"/api/categories/{parent['id']}?move_to={keeper['id']}")
    assert deleted.json() == {"result": "deleted", "moved": 2, "removed": 2}

    remaining = {item["id"] for item in (await auth_client.get("/api/categories")).json()}
    assert parent["id"] not in remaining
    assert child["id"] not in remaining


async def test_replacement_must_make_sense(auth_client: httpx.AsyncClient):
    parent = (await auth_client.post("/api/categories", json={"name": "Супермаркет"})).json()
    child = (
        await auth_client.post(
            "/api/categories", json={"name": "Пятёрочка", "parent_id": parent["id"]}
        )
    ).json()
    income = (
        await auth_client.post("/api/categories", json={"name": "Премия", "kind": "income"})
    ).json()
    await auth_client.post(
        "/api/transactions",
        json={"type": "expense", "amount": "100", "category_id": child["id"]},
    )

    # Внутрь удаляемого поддерева переносить некуда — эта категория тоже исчезнет
    into_subtree = await auth_client.delete(
        f"/api/categories/{parent['id']}?move_to={child['id']}"
    )
    assert into_subtree.status_code == 400

    # Расходы не переезжают в доходную категорию
    wrong_kind = await auth_client.delete(f"/api/categories/{parent['id']}?move_to={income['id']}")
    assert wrong_kind.status_code == 400

    unknown = await auth_client.delete(f"/api/categories/{parent['id']}?move_to=нет-такой")
    assert unknown.status_code == 400

    # После трёх отказов дерево на месте
    remaining = {item["id"] for item in (await auth_client.get("/api/categories")).json()}
    assert {parent["id"], child["id"]} <= remaining


async def test_deleted_transactions_do_not_keep_a_dead_category(auth_client: httpx.AsyncClient):
    """Мягко удалённая операция тоже переезжает: ссылка на стёртую категорию — мусор."""
    doomed = (await auth_client.post("/api/categories", json={"name": "Кальян"})).json()
    keeper = (await auth_client.post("/api/categories", json={"name": "Привычки"})).json()
    tx = (
        await auth_client.post(
            "/api/transactions",
            json={"type": "expense", "amount": "100", "category_id": doomed["id"]},
        )
    ).json()
    await auth_client.delete(f"/api/transactions/{tx['id']}")

    # Живых операций нет, поэтому замену не требуем, но передать её всё равно можно
    usage = (await auth_client.get(f"/api/categories/{doomed['id']}/usage")).json()
    assert usage["needs_replacement"] is False

    deleted = await auth_client.delete(f"/api/categories/{doomed['id']}?move_to={keeper['id']}")
    assert deleted.status_code == 200
    # Перенос был, но в счётчик он не попал: перевыгружать удалённую строку незачем
    assert deleted.json()["moved"] == 0


async def test_rules_follow_the_category(seeded: AsyncSession):
    """Правило «пятёроч → …» должно пережить удаление категории, иначе быстрый ввод немеет."""
    doomed = await _root(seeded, "Кальянная")
    keeper = await _root(seeded, "Привычки")
    await categories_repo.add_rule(seeded, pattern="кальян", category_id=doomed.id)

    await catalog.delete_category(seeded, doomed, move_to=keeper.id)

    rules = await categories_repo.list_rules(seeded)
    assert [rule.category_id for rule in rules if rule.pattern == "кальян"] == [keeper.id]


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
