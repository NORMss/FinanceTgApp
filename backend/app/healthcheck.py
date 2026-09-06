"""Проба живости для docker healthcheck: `python -m app.healthcheck`.

Отдельный модуль, а не строчка в compose, по двум причинам.

Первая — вес. Проба запускается раз в полминуты внутри контейнера с лимитом памяти,
и её пик считается в тот же лимит, что и приложение. Прежний вариант поднимал urllib
(~25 МБ на процесс); голого сокета хватает на те же 8 байт статуса, и стоит он вдвое
меньше. При тесном лимите такой всплеск рядом с работающим приложением — лишний повод
для OOM-killer'а выбрать жертву, а жертвой он выбирает самый крупный процесс, то есть
само приложение.

Вторая — HTTP/1.0 и Connection: close. Проба не оставляет за собой keep-alive-соединение,
которое сервер потом держит и закрывает по таймауту.
"""

import socket
import sys

HOST = "127.0.0.1"
PORT = 8000
TIMEOUT = 5
REQUEST = b"GET /api/health HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n"


def probe(host: str = HOST, port: int = PORT, timeout: float = TIMEOUT) -> bool:
    try:
        with socket.create_connection((host, port), timeout) as connection:
            connection.sendall(REQUEST)
            # Статус лежит в первой строке — читать тело незачем
            return b" 200 " in connection.recv(64)
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(0 if probe() else 1)
