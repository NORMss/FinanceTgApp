"""Тонкая обёртка над Google Sheets API v4.

Библиотека Google синхронная, поэтому каждый вызов уходит в поток через asyncio.to_thread —
иначе он заблокирует event loop приложения на всю сетевую задержку.

Про режимы записи: используем RAW. При USER_ENTERED таблица переинтерпретирует наши строки
по локали (дата «2026-08-11 14:30» превратится в «11.08.2026»), и обратный импорт начнёт
считать каждую строку отредактированной вручную. При RAW числа остаются числами
(в JSON они уходят числами), а текст — ровно тем текстом, что мы записали.
"""

import asyncio
import logging
import random
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5


class SheetsUnavailable(RuntimeError):
    """Google недоступен или квота исчерпана. Воркер оставит записи в outbox и повторит позже."""


class SheetsClient:
    def __init__(self, spreadsheet_id: str, credentials_file: str) -> None:
        self._spreadsheet_id = spreadsheet_id
        self._credentials_file = credentials_file
        self._service: Any | None = None

    @classmethod
    def from_settings(cls) -> "SheetsClient":
        return cls(settings.google_spreadsheet_id, str(settings.google_credentials_file))

    def _get_service(self) -> Any:
        if self._service is None:
            credentials = Credentials.from_service_account_file(
                self._credentials_file, scopes=SCOPES
            )
            # cache_discovery=False: иначе клиент лезет писать кэш на диск и шумит предупреждениями
            self._service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return self._service

    async def _call(self, build_request):  # noqa: ANN001
        """Выполняет запрос с усечённой экспоненциальной задержкой — как рекомендует Google."""
        delay = 1.0
        last_error: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return await asyncio.to_thread(lambda: build_request(self._get_service()).execute())
            except HttpError as exc:
                status = getattr(exc.resp, "status", None)
                last_error = exc
                if status not in RETRYABLE_STATUS or attempt == MAX_ATTEMPTS:
                    raise SheetsUnavailable(f"Sheets API {status}: {exc}") from exc
                sleep_for = delay + random.uniform(0, 0.5)
                log.warning("Sheets %s, попытка %s, ждём %.1fс", status, attempt, sleep_for)
                await asyncio.sleep(sleep_for)
                delay *= 2
            except OSError as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS:
                    raise SheetsUnavailable(f"сеть недоступна: {exc}") from exc
                await asyncio.sleep(delay)
                delay *= 2

        raise SheetsUnavailable(str(last_error))

    async def sheet_titles(self) -> list[str]:
        response = await self._call(
            lambda service: service.spreadsheets().get(
                spreadsheetId=self._spreadsheet_id, fields="sheets.properties.title"
            )
        )
        return [sheet["properties"]["title"] for sheet in response.get("sheets", [])]

    async def create_sheet(self, title: str) -> None:
        await self._call(
            lambda service: service.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
            )
        )

    async def get_values(self, range_: str) -> list[list]:
        response = await self._call(
            lambda service: service.spreadsheets()
            .values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=range_,
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="FORMATTED_STRING",
            )
        )
        return response.get("values", [])

    async def update_values(self, updates: list[tuple[str, list[list]]]) -> None:
        """Пачка точечных обновлений одним запросом — экономит квоту (60 записей/мин)."""
        if not updates:
            return
        body = {
            "valueInputOption": "RAW",
            "data": [{"range": range_, "values": values} for range_, values in updates],
        }
        await self._call(
            lambda service: service.spreadsheets()
            .values()
            .batchUpdate(spreadsheetId=self._spreadsheet_id, body=body)
        )

    async def append_values(self, range_: str, values: list[list]) -> None:
        if not values:
            return
        await self._call(
            lambda service: service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self._spreadsheet_id,
                range=range_,
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            )
        )

    @property
    def spreadsheet_url(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}/edit"
