"""Диагностика доступа к Google Sheets.

    python -m app.sync.check

Проверяет всю цепочку по порядку: настройки -> ключ сервис-аккаунта -> права на таблицу.
Ошибки Google приходят однотипным HttpError, по которому непонятно, что чинить, поэтому
каждый код здесь переводится в конкретное действие.
"""

import sys

from googleapiclient.errors import HttpError

from app.config import settings
from app.sync.client import SheetsClient


def _explain(error: HttpError, service_account: str) -> str:
    status = getattr(error.resp, "status", None)
    text = str(error)

    if status == 404:
        return (
            "Таблица не найдена. Проверьте GOOGLE_SPREADSHEET_ID — это часть адреса\n"
            "между /d/ и /edit, а не название файла и не весь URL."
        )
    if status == 403 and "has not been used in project" in text:
        return (
            "В проекте Google Cloud не включён Google Sheets API.\n"
            "Включите его: APIs & Services -> Library -> Google Sheets API -> Enable."
        )
    if status in (401, 403):
        return (
            "Нет доступа к таблице. Права на файл выдаются НЕ в Google Cloud Console,\n"
            "а в самой таблице:\n"
            f"  1. откройте её в браузере под владельцем;\n"
            f"  2. «Поделиться» -> вставьте {service_account};\n"
            "  3. выберите роль «Редактор» и подтвердите.\n"
            "Если аккаунт корпоративный, политика Workspace может запрещать выдачу прав\n"
            "адресам вне организации — тогда перенесите таблицу на личный аккаунт."
        )
    return f"Неожиданный ответ Google: {text}"


def main() -> int:
    print("— настройки —")
    print(f"SHEETS_ENABLED:        {settings.sheets_enabled}")
    print(f"GOOGLE_SPREADSHEET_ID: {settings.google_spreadsheet_id or '(не задан)'}")
    print(f"файл ключа:            {settings.google_credentials_file}")

    if not settings.google_spreadsheet_id:
        print("\nНе задан GOOGLE_SPREADSHEET_ID — брать из адреса таблицы между /d/ и /edit.")
        return 1
    if not settings.google_credentials_file.exists():
        print("\nФайл ключа не найден. Положите JSON сервис-аккаунта по этому пути.")
        return 1

    client = SheetsClient.from_settings()
    try:
        service = client._get_service()  # noqa: SLF001 — диагностика лезет во внутренности осознанно
        service_account = service._http.credentials.service_account_email  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        print(f"\nКлюч не читается: {exc}")
        print("Скорее всего файл повреждён при копировании — перенесите его через scp.")
        return 1

    print(f"сервис-аккаунт:        {service_account}")

    print("\n— доступ к таблице —")
    try:
        meta = (
            service.spreadsheets()
            .get(
                spreadsheetId=settings.google_spreadsheet_id,
                fields="properties.title,sheets.properties.title",
            )
            .execute()
        )
    except HttpError as exc:
        print(f"Не получилось: HTTP {getattr(exc.resp, 'status', '?')}\n")
        print(_explain(exc, service_account))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"Не получилось: {exc}")
        if "invalid_grant" in str(exc):
            print(
                "\nGoogle не признаёт этот ключ: сервис-аккаунт удалён либо ключ отозван.\n"
                "Создайте новый ключ в Cloud Console (Service accounts -> Keys -> Add key)\n"
                "и не забудьте заново выдать доступ к таблице новому адресу."
            )
        return 1

    titles = [sheet["properties"]["title"] for sheet in meta.get("sheets", [])]
    print(f"название:  {meta['properties']['title']}")
    print(f"листы:     {', '.join(titles) or '(нет)'}")
    print(f"\nВсё в порядке: {client.spreadsheet_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
