"""ULID без внешних зависимостей.

ULID = 48 бит времени (мс) + 80 бит случайности, Crockford Base32, 26 символов.
Берём его вместо UUID4, потому что он лексикографически сортируется по времени создания:
это удобно и для индексов SQLite, и для строк в Google Sheets.
"""

import secrets
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_LENGTH = 26


def new_ulid(timestamp_ms: int | None = None) -> str:
    ts = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    value = (ts << 80) | secrets.randbits(80)
    return "".join(_ALPHABET[(value >> (5 * (_LENGTH - 1 - i))) & 0x1F] for i in range(_LENGTH))


def is_ulid(value: str) -> bool:
    return len(value) == _LENGTH and all(char in _ALPHABET for char in value)
