from fastapi import APIRouter, Response, status

from app.db import healthcheck

router = APIRouter(tags=["service"])


@router.api_route("/health", methods=["GET", "HEAD"])
async def health(response: Response) -> dict:
    """Проверка живости для docker healthcheck и мониторинга.

    Отвечает одним словом. Раньше здесь были версия приложения, режим бота и состояние
    Google Sheets — удобно при отладке, но это же и готовая карточка сервиса для любого,
    кто нашёл адрес: по версии подбирают известные дыры. Всё то же самое пишется в лог
    при старте, где оно доступно владельцу и никому больше.
    """
    try:
        db_ok = await healthcheck()
    except Exception:  # noqa: BLE001 — наружу отдаём статус, а не трейс
        db_ok = False

    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded"}
    return {"status": "ok"}
