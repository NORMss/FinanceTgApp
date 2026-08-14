"""Ограничение частоты неудачных входов.

Вход в Mini App — единственная ручка, доступная без токена, поэтому именно её будут
долбить, если найдут адрес. Подобрать подпись initData без токена бота нельзя, но
бесконечно проверять попытки всё равно не стоит: это и нагрузка, и шум в логах.

Счётчик держим в памяти процесса. Приложение однопроцессное (в Dockerfile `--workers 1`),
и переживать перезапуск счётчику незачем — он защищает от потока попыток здесь и сейчас,
а не заменяет firewall.
"""

import time
from collections import deque
from dataclasses import dataclass, field
from ipaddress import ip_address

from fastapi import Request

# Больше адресов в памяти держать незачем: столько разных клиентов у приватного
# приложения на двоих не бывает, а без границы словарь растёт от любого сканера
MAX_TRACKED_CLIENTS = 2048


@dataclass(slots=True)
class _Window:
    hits: deque[float] = field(default_factory=deque)


class RateLimiter:
    """Скользящее окно: N событий за T секунд с одного ключа."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._clients: dict[str, _Window] = {}

    def _prune(self, key: str, now: float) -> _Window:
        window = self._clients.get(key)
        if window is None:
            if len(self._clients) >= MAX_TRACKED_CLIENTS:
                self._forget_oldest(now)
            window = self._clients.setdefault(key, _Window())
        while window.hits and now - window.hits[0] > self.window:
            window.hits.popleft()
        return window

    def _forget_oldest(self, now: float) -> None:
        stale = [
            key
            for key, window in self._clients.items()
            if not window.hits or now - window.hits[-1] > self.window
        ]
        for key in stale:
            del self._clients[key]
        if len(self._clients) >= MAX_TRACKED_CLIENTS:
            self._clients.clear()

    def is_blocked(self, key: str) -> bool:
        return len(self._prune(key, time.monotonic()).hits) >= self.limit

    def register_failure(self, key: str) -> None:
        now = time.monotonic()
        self._prune(key, now).hits.append(now)

    def reset(self, key: str) -> None:
        """Успешный вход стирает историю: живой пользователь не должен ловить блокировку
        из-за того, что до него с того же адреса кто-то ошибался."""
        self._clients.pop(key, None)

    def retry_after(self, key: str) -> int:
        window = self._prune(key, time.monotonic())
        if not window.hits:
            return 0
        return max(1, int(self.window - (time.monotonic() - window.hits[0])))


def client_key(request: Request, *, trust_proxy: bool) -> str:
    """Адрес клиента. За прокси реальный адрес приходит в X-Forwarded-For.

    Заголовку верим только когда так настроено: если приложение опубликовано напрямую,
    любой может прислать чужой X-Forwarded-For и либо обойти лимит, либо подставить соседа.
    """
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            try:
                return str(ip_address(first))
            except ValueError:
                pass  # мусор в заголовке — считаем адрес неизвестным и падаем на socket
    return request.client.host if request.client else "unknown"
