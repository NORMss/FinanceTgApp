"""Разбор фильтров отчёта из query string.

Один хелпер на список операций, сводку и выгрузку — по той же причине, по которой
один `period_bounds` обслуживает все периоды: фильтры, разъехавшиеся между отчётом
и историей, дают две разные суммы на одни и те же условия, и человек справедливо
перестаёт верить обеим.

Здесь же живёт раскрытие дерева: выбранная или скрытая категория всегда тянет за
собой подкатегории, и решать это должен сервер, а не каждый клиент по-своему.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status

from app.models import TransactionType
from app.repositories.transactions import TxFilter
from app.services import catalog as catalog_service
from app.util.tags import parse_tags

# Потолок на длину любого списка в фильтре. Категорий в живом справочнике десятки,
# меток — единицы; тысяча идентификаторов в запросе означает не отчёт, а попытку
# нагрузить ручку. Тот же порядок, что у `limit` в списке операций
MAX_IDS = 200


@dataclass(slots=True)
class FilterParams:
    """Сырые фильтры из запроса — до раскрытия дерева категорий."""

    # «Чья трата» — про деньги, этим фильтруют история и отчёт
    person_ids: list[str] = field(default_factory=list)
    # «Кто записал» — про действие ввода. Совпадают не всегда: запись за другого
    # делается с его личного счёта, и принадлежит она ему, а не автору
    author_ids: list[str] = field(default_factory=list)
    category_ids: list[str] = field(default_factory=list)
    account_ids: list[str] = field(default_factory=list)
    exclude_category_ids: list[str] = field(default_factory=list)
    exclude_uncategorized: bool = False
    tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)
    search: str | None = None


def _capped(values: list[str] | None, name: str) -> list[str]:
    items = values or []
    if len(items) > MAX_IDS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"слишком длинный список {name}: максимум {MAX_IDS}"
        )
    return items


def filter_params(
    person_ids: Annotated[list[str] | None, Query()] = None,
    author_ids: Annotated[list[str] | None, Query()] = None,
    category_ids: Annotated[list[str] | None, Query()] = None,
    account_ids: Annotated[list[str] | None, Query()] = None,
    exclude_category_ids: Annotated[list[str] | None, Query()] = None,
    exclude_uncategorized: bool = Query(False),
    tags: Annotated[list[str] | None, Query()] = None,
    exclude_tags: Annotated[list[str] | None, Query()] = None,
    search: str | None = Query(None),
) -> FilterParams:
    return FilterParams(
        person_ids=_capped(person_ids, "person_ids"),
        author_ids=_capped(author_ids, "author_ids"),
        category_ids=_capped(category_ids, "category_ids"),
        account_ids=_capped(account_ids, "account_ids"),
        exclude_category_ids=_capped(exclude_category_ids, "exclude_category_ids"),
        exclude_uncategorized=exclude_uncategorized,
        # Метки нормализуем так же, как при записи: иначе «Отпуск» из ссылки
        # не найдёт «отпуск» в базе
        tags=parse_tags(",".join(_capped(tags, "tags"))),
        exclude_tags=parse_tags(",".join(_capped(exclude_tags, "exclude_tags"))),
        search=search,
    )


FiltersDep = Annotated[FilterParams, Depends(filter_params)]


async def build(
    session,
    params: FilterParams,
    bounds: tuple[datetime, datetime],
    *,
    types: list[TransactionType] | None = None,
) -> TxFilter:
    """Собирает `TxFilter`, раскрывая категории до подкатегорий.

    Раскрываются обе стороны: выбрали «Продукты» — считаем и «Пятёрочку»; скрыли
    «Жильё» — скрывается и «Коммуналка». Несимметричное поведение здесь было бы
    ловушкой: человек прячет ветку целиком, а половина её остаётся в итоге.
    """
    start, end = bounds
    return TxFilter(
        start=start,
        end=end,
        types=types or [],
        category_ids=await catalog_service.expand_ids(session, params.category_ids),
        account_ids=params.account_ids,
        person_ids=params.person_ids,
        author_ids=params.author_ids,
        search=params.search,
        exclude_category_ids=await catalog_service.expand_ids(
            session, params.exclude_category_ids
        ),
        exclude_uncategorized=params.exclude_uncategorized,
        tags=params.tags,
        exclude_tags=params.exclude_tags,
    )
