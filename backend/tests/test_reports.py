"""Экран отчёта: период, исключения, сравнение, лимиты, метки, сохранённые виды.

Проверяется в основном через HTTP: отчёт — это ответ одной ручки целиком, и ловить
в нём расхождения удобнее там же, где их увидит клиент.
"""

import httpx
import pytest

from app.util.dates import add_months, now


async def categories(client: httpx.AsyncClient) -> list[dict]:
    return (await client.get("/api/categories")).json()


async def tree(client: httpx.AsyncClient) -> tuple[dict, dict]:
    """Корневая категория расходов, у которой есть хотя бы одна подкатегория."""
    items = await categories(client)
    parent = next(
        item
        for item in items
        if item["kind"] == "expense"
        and not item["parent_id"]
        and any(child["parent_id"] == item["id"] for child in items)
    )
    child = next(item for item in items if item["parent_id"] == parent["id"])
    return parent, child


async def spend(client: httpx.AsyncClient, amount: str, **extra) -> dict:
    payload = {"type": "expense", "amount": amount, **extra}
    response = await client.post("/api/transactions", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def summary(client: httpx.AsyncClient, query: str = "") -> dict:
    response = await client.get(f"/api/stats/summary?period=month{query}")
    assert response.status_code == 200, response.text
    return response.json()


def row(data: dict, name: str) -> dict:
    return next(item for item in data["by_category"] if item["name"] == name)


# --- Д1: дерево категорий -------------------------------------------------


async def test_uncategorized_does_not_duplicate_roots(auth_client: httpx.AsyncClient):
    """Операция без категории не должна утаскивать под себя все корневые категории.

    Раньше «Без категории» становилась родителем каждой корневой — у них
    parent_id тоже None, — и отчёт печатал их дважды, а доли давали под 200 %.
    """
    parent, child = await tree(auth_client)
    other = next(
        item
        for item in await categories(auth_client)
        if item["kind"] == "expense" and not item["parent_id"] and item["id"] != parent["id"]
    )

    await spend(auth_client, "100", category_id=parent["id"])
    await spend(auth_client, "50", category_id=child["id"])
    await spend(auth_client, "70", category_id=other["id"])
    await spend(auth_client, "30")  # без категории

    data = await summary(auth_client)
    names = [item["name"] for item in data["by_category"]]
    assert len(names) == len(set(names)), f"категория продублирована: {names}"

    roots = [item for item in data["by_category"] if not item["parent_id"]]
    assert sum(item["share"] for item in roots) == pytest.approx(1.0)
    assert sum(item["amount_minor"] for item in roots) == data["expense_minor"]


# --- Д2: доходы под категорийным фильтром ---------------------------------


async def test_category_filter_keeps_income_intact(auth_client: httpx.AsyncClient):
    """«Покажи Продукты» ограничивает расходы, а не обнуляет зарплату.

    Раньше фильтр применялся к обеим сторонам сразу: доходных операций в расходной
    категории нет ни одной, поэтому доход честно получался нулевым, а сальдо —
    отрицательным при живой зарплате.
    """
    parent, _ = await tree(auth_client)
    await spend(auth_client, "100", category_id=parent["id"])
    await spend(auth_client, "50")
    await auth_client.post("/api/transactions", json={"type": "income", "amount": "1000"})

    data = await summary(auth_client, f"&category_ids={parent['id']}")
    assert data["expense_minor"] == 10_000
    assert data["income_minor"] == 100_000
    assert data["net_minor"] == 90_000


# --- R1: исключения --------------------------------------------------------


async def test_excluding_parent_takes_the_whole_branch(auth_client: httpx.AsyncClient):
    parent, child = await tree(auth_client)
    await spend(auth_client, "100", category_id=parent["id"])
    await spend(auth_client, "50", category_id=child["id"])
    await spend(auth_client, "70")

    data = await summary(auth_client, f"&exclude_category_ids={parent['id']}")
    assert data["expense_minor"] == 7_000
    assert [item["name"] for item in data["by_category"]] == ["Без категории"]


async def test_excluding_child_only_reduces_parent(auth_client: httpx.AsyncClient):
    parent, child = await tree(auth_client)
    await spend(auth_client, "100", category_id=parent["id"])
    await spend(auth_client, "50", category_id=child["id"])

    data = await summary(auth_client, f"&exclude_category_ids={child['id']}")
    assert data["expense_minor"] == 10_000
    assert row(data, parent["name"])["amount_minor"] == 10_000
    assert all(item["name"] != child["name"] for item in data["by_category"])


async def test_exclusion_keeps_operations_without_category(auth_client: httpx.AsyncClient):
    """Д3: `NOT IN` в SQL роняет строки с NULL — операции без категории обязаны остаться."""
    parent, _ = await tree(auth_client)
    await spend(auth_client, "100", category_id=parent["id"])
    await spend(auth_client, "70")

    data = await summary(auth_client, f"&exclude_category_ids={parent['id']}")
    assert data["expense_minor"] == 7_000, "операция без категории пропала из итога"

    both = await summary(
        auth_client, f"&exclude_category_ids={parent['id']}&exclude_uncategorized=true"
    )
    assert both["expense_minor"] == 0


async def test_excluded_amount_reconciles_with_total(auth_client: httpx.AsyncClient):
    """Скрытое плюс показанное равно полной сумме — иначе цифре нельзя верить."""
    parent, child = await tree(auth_client)
    await spend(auth_client, "100", category_id=parent["id"])
    await spend(auth_client, "50", category_id=child["id"])
    await spend(auth_client, "70")

    full = await summary(auth_client)
    filtered = await summary(auth_client, f"&exclude_category_ids={parent['id']}")

    assert filtered["excluded_minor"] == 15_000
    assert filtered["excluded_count"] == 2
    assert filtered["expense_minor"] + filtered["excluded_minor"] == full["expense_minor"]
    assert full["excluded_minor"] == 0, "без исключений скрывать нечего"


async def test_report_and_history_agree_on_exclusions(auth_client: httpx.AsyncClient):
    """Провал из отчёта в историю обязан показать ровно те операции, из которых
    сложилась цифра. Для этого у обеих ручек один разбор фильтров."""
    parent, _ = await tree(auth_client)
    await spend(auth_client, "100", category_id=parent["id"])
    await spend(auth_client, "70")

    query = f"period=month&exclude_category_ids={parent['id']}"
    data = (await auth_client.get(f"/api/stats/summary?{query}")).json()
    listing = (await auth_client.get(f"/api/transactions?{query}&types=expense")).json()

    assert listing["total"] == 1
    assert sum(item["amount_minor"] for item in listing["items"]) == data["expense_minor"]


async def test_too_many_ids_rejected(auth_client: httpx.AsyncClient):
    query = "&".join(f"exclude_category_ids=id{i}" for i in range(201))
    response = await auth_client.get(f"/api/stats/summary?period=month&{query}")
    assert response.status_code == 400


# --- R2: произвольный период ----------------------------------------------


async def test_custom_date_range(auth_client: httpx.AsyncClient):
    today = now().date()
    await spend(auth_client, "100")

    inside = (
        await auth_client.get(f"/api/stats/summary?from={today}&to={today}")
    ).json()
    assert inside["expense_minor"] == 10_000

    tomorrow = add_months(today.replace(day=1), 1)
    outside = (
        await auth_client.get(f"/api/stats/summary?from={tomorrow}&to={tomorrow}")
    ).json()
    assert outside["expense_minor"] == 0
    assert outside["count"] == 0


# --- R8: сравнение с предыдущим периодом ----------------------------------


async def test_compare_with_previous_month(auth_client: httpx.AsyncClient):
    parent, _ = await tree(auth_client)
    this_month = now().replace(day=2, hour=12)
    last_month = this_month.replace(
        year=add_months(this_month.date(), -1).year,
        month=add_months(this_month.date(), -1).month,
    )

    await spend(
        auth_client, "100", category_id=parent["id"], occurred_at=this_month.isoformat()
    )
    await spend(
        auth_client, "60", category_id=parent["id"], occurred_at=last_month.isoformat()
    )

    plain = await summary(auth_client)
    assert plain["previous"] is None, "без compare предыдущий период не считаем"

    data = await summary(auth_client, "&compare=true")
    assert data["expense_minor"] == 10_000
    assert data["previous"]["expense_minor"] == 6_000
    assert row(data, parent["name"])["previous_minor"] == 6_000


async def test_all_time_has_no_previous_period(auth_client: httpx.AsyncClient):
    await spend(auth_client, "100")
    data = (await auth_client.get("/api/stats/summary?period=all&compare=true")).json()
    assert data["previous"] is None


# --- R9: крупнейшие траты --------------------------------------------------


async def test_largest_spends_are_sorted_by_amount(auth_client: httpx.AsyncClient):
    for amount in ("100", "5000", "300", "80", "1200", "40", "60"):
        await spend(auth_client, amount)

    data = await summary(auth_client)
    assert [item["amount_minor"] for item in data["largest"]] == [
        500_000, 120_000, 30_000, 10_000, 8_000
    ]


# --- R10: разбивка доходов -------------------------------------------------


async def test_income_breakdown(auth_client: httpx.AsyncClient):
    salary = next(
        item for item in await categories(auth_client) if item["kind"] == "income"
    )
    await auth_client.post(
        "/api/transactions",
        json={"type": "income", "amount": "70000", "category_id": salary["id"]},
    )
    await spend(auth_client, "100")

    data = await summary(auth_client)
    assert [item["name"] for item in data["by_income_category"]] == [salary["name"]]
    assert data["by_income_category"][0]["amount_minor"] == 7_000_000
    # Расходная разбивка при этом не смешивается с доходной
    assert all(item["name"] != salary["name"] for item in data["by_category"])


# --- R12: фильтр по счёту --------------------------------------------------


async def test_account_filter(auth_client: httpx.AsyncClient):
    personal = (await auth_client.get("/api/accounts")).json()[0]
    shared = (
        await auth_client.post(
            "/api/accounts", json={"name": "Общий счёт", "is_shared": True}
        )
    ).json()

    await spend(auth_client, "100", account_id=personal["id"])
    await spend(auth_client, "40", account_id=shared["id"])

    only_shared = await summary(auth_client, f"&account_ids={shared['id']}")
    assert only_shared["expense_minor"] == 4_000


# --- R11: по автору против по долям ---------------------------------------


async def test_spender_differs_from_author_on_shared_account(
    auth_client: httpx.AsyncClient, client: httpx.AsyncClient
):
    """С общего счёта трату записал один, а досталась она обоим.

    `by_author` отвечает «кто записал», `by_spender` — «чья это трата». На общем
    счёте цифры расходятся ровно вдвое, и показывать только первую значит каждый
    месяц объяснять, почему один «тратит» вдвое больше другого.
    """
    from app.security.initdata import build_init_data
    from tests.conftest import USER_B

    # Второй участник должен существовать, иначе делить не с кем
    init_data = build_init_data("123456:TEST-TOKEN", USER_B)
    assert (await client.post("/api/auth/login", json={"init_data": init_data})).status_code == 200

    shared = (
        await auth_client.post(
            "/api/accounts", json={"name": "Общий счёт", "is_shared": True}
        )
    ).json()
    await spend(auth_client, "400", account_id=shared["id"])

    data = await summary(auth_client)
    by_author = {item["name"]: item["amount_minor"] for item in data["by_author"]}
    by_spender = {item["name"]: item["amount_minor"] for item in data["by_spender"]}

    assert by_author == {"Аня": 40_000}
    assert by_spender == {"Аня": 20_000, "Боря": 20_000}


# --- R16: лимиты -----------------------------------------------------------


async def test_budget_shows_up_for_whole_month_only(auth_client: httpx.AsyncClient):
    parent, _ = await tree(auth_client)
    saved = await auth_client.put(
        f"/api/budgets/{parent['id']}", json={"limit": "25 000"}
    )
    assert saved.status_code == 200
    assert saved.json()["limit_minor"] == 2_500_000

    await spend(auth_client, "100", category_id=parent["id"])

    monthly = await summary(auth_client)
    assert row(monthly, parent["name"])["limit_minor"] == 2_500_000

    # За неделю лимит не отдаём: «17 % от месячного» за неделю ничего не значит
    weekly = (await auth_client.get("/api/stats/summary?period=week")).json()
    assert all(item["limit_minor"] == 0 for item in weekly["by_category"])


async def test_budget_crud(auth_client: httpx.AsyncClient):
    parent, _ = await tree(auth_client)
    await auth_client.put(f"/api/budgets/{parent['id']}", json={"limit": "1000"})
    assert (await auth_client.get("/api/budgets")).json() == [
        {"category_id": parent["id"], "limit_minor": 100_000}
    ]

    # Повторный PUT перезаписывает, а не заводит второй лимит на ту же категорию
    await auth_client.put(f"/api/budgets/{parent['id']}", json={"limit": "1500"})
    assert (await auth_client.get("/api/budgets")).json()[0]["limit_minor"] == 150_000

    assert (await auth_client.delete(f"/api/budgets/{parent['id']}")).status_code == 204
    assert (await auth_client.get("/api/budgets")).json() == []
    assert (await auth_client.delete(f"/api/budgets/{parent['id']}")).status_code == 404


async def test_budget_rejects_unknown_category_and_negative_limit(
    auth_client: httpx.AsyncClient,
):
    missing = await auth_client.put("/api/budgets/нет-такой", json={"limit": "10"})
    assert missing.status_code == 404

    parent, _ = await tree(auth_client)
    bad = await auth_client.put(f"/api/budgets/{parent['id']}", json={"limit": "-5"})
    assert bad.status_code == 400


# --- R17: повторяющиеся траты ---------------------------------------------


async def test_repeated_notes(auth_client: httpx.AsyncClient):
    # Один и тот же платёж, записанный тремя разными руками: разный регистр
    # и лишние пробелы — это по-прежнему одна подписка
    for note in ("Яндекс Плюс", "яндекс плюс", "  Яндекс   Плюс  "):
        await spend(auth_client, "299", note=note)
    await spend(auth_client, "1000", note="разовая покупка")

    data = await summary(auth_client)
    notes = {item["note"]: item for item in data["repeated"]}
    assert "яндекс плюс" in notes, "регистр не должен разбивать одну подписку на три"
    assert notes["яндекс плюс"]["count"] == 3
    assert notes["яндекс плюс"]["total_minor"] == 89_700
    assert "разовая покупка" not in notes, "однократная трата — не повторяющаяся"


# --- R18: метки ------------------------------------------------------------


async def test_tags_are_normalized_on_write(auth_client: httpx.AsyncClient):
    created = await spend(auth_client, "100", tags="  Отпуск , отпуск,  ТУРЦИЯ ")
    assert created["tags"] == "отпуск,турция"


async def test_filter_and_exclude_by_tag(auth_client: httpx.AsyncClient):
    await spend(auth_client, "100", tags="отпуск")
    await spend(auth_client, "50", tags="отпуск,такси")
    await spend(auth_client, "70")

    only = await summary(auth_client, "&tags=Отпуск")
    assert only["expense_minor"] == 15_000, "фильтр по метке нечувствителен к регистру"

    without = await summary(auth_client, "&exclude_tags=отпуск")
    assert without["expense_minor"] == 7_000
    assert without["excluded_minor"] == 15_000


async def test_tag_match_is_whole_word(auth_client: httpx.AsyncClient):
    """«отпуск» не должен находить «отпускные» — метки лежат одной строкой через запятую."""
    await spend(auth_client, "100", tags="отпускные")
    assert (await summary(auth_client, "&tags=отпуск"))["expense_minor"] == 0


async def test_known_tags_listing(auth_client: httpx.AsyncClient):
    await spend(auth_client, "100", tags="отпуск,такси")
    await spend(auth_client, "50", tags="отпуск")

    tags = (await auth_client.get("/api/tags")).json()
    assert tags == [{"name": "отпуск", "count": 2}, {"name": "такси", "count": 1}]


# --- R19: сохранённые виды -------------------------------------------------


async def test_report_views_crud(auth_client: httpx.AsyncClient):
    payload = {"period": "month", "excludeCategoryIds": ["a", "b"]}
    created = await auth_client.post(
        "/api/report-views", json={"name": "Без ипотеки", "payload": payload}
    )
    assert created.status_code == 201, created.text
    assert created.json()["payload"] == payload

    listing = (await auth_client.get("/api/report-views")).json()
    assert [item["name"] for item in listing] == ["Без ипотеки"]

    # Сохранение под тем же именем перезаписывает: «я поправил фильтры»,
    # а не «заведи второй вид с тем же названием»
    again = await auth_client.post(
        "/api/report-views", json={"name": "Без ипотеки", "payload": {"period": "year"}}
    )
    assert again.status_code == 201
    assert len((await auth_client.get("/api/report-views")).json()) == 1

    view_id = again.json()["id"]
    assert (await auth_client.delete(f"/api/report-views/{view_id}")).status_code == 204
    assert (await auth_client.get("/api/report-views")).json() == []


async def test_report_view_of_another_user_is_invisible(
    auth_client: httpx.AsyncClient, client: httpx.AsyncClient
):
    from app.security.initdata import build_init_data
    from tests.conftest import USER_B

    mine = (
        await auth_client.post("/api/report-views", json={"name": "Мой", "payload": {}})
    ).json()

    init_data = build_init_data("123456:TEST-TOKEN", USER_B)
    token = (await client.post("/api/auth/login", json={"init_data": init_data})).json()["token"]
    other = {"Authorization": f"Bearer {token}"}

    assert (await client.get("/api/report-views", headers=other)).json() == []
    # Чужой вид отдаётся как несуществующий — подтверждать его существование незачем
    dropped = await client.delete(f"/api/report-views/{mine['id']}", headers=other)
    assert dropped.status_code == 404


# --- R15: динамика по месяцам ----------------------------------------------


async def test_trend_groups_by_month_and_rolls_up_subcategories(
    auth_client: httpx.AsyncClient,
):
    parent, child = await tree(auth_client)
    this_month = now().replace(day=2, hour=12)
    previous = add_months(this_month.date(), -1)
    last_month = this_month.replace(year=previous.year, month=previous.month)

    await spend(
        auth_client, "100", category_id=parent["id"], occurred_at=this_month.isoformat()
    )
    await spend(
        auth_client, "50", category_id=child["id"], occurred_at=this_month.isoformat()
    )
    await spend(
        auth_client, "60", category_id=child["id"], occurred_at=last_month.isoformat()
    )

    data = (await auth_client.get("/api/stats/trend?period=year")).json()
    assert len(data["months"]) >= 2
    assert sum(data["expense"]) == 21_000

    # Подкатегория свёрнута в корень: на графике «Пятёрочка» и «Магнит» отдельными
    # линиями не помещаются, а разбивка осталась в списке отчёта
    names = [item["name"] for item in data["categories"]]
    assert parent["name"] in names
    assert child["name"] not in names


# --- R14: отправка в чат ---------------------------------------------------


async def test_share_reports_bot_is_off(auth_client: httpx.AsyncClient):
    """В тестах BOT_MODE=off — ручка обязана сказать это словами, а не упасть."""
    response = await auth_client.post("/api/stats/share?period=month")
    assert response.status_code == 503
    assert "бот" in response.json()["detail"]
