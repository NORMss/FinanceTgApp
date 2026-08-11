"""Деньги — всегда целые в минорных единицах (копейках).

Ни одного float в кодовой базе: 0.1 + 0.2 != 0.3, а в учёте финансов это неприемлемо.
На границе с пользователем конвертируем строку <-> int, внутри работаем только с int.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Валюты без дробной части. Список неполный — расширяется по мере надобности.
_ZERO_DECIMAL = {"JPY", "KRW", "VND", "CLP", "ISK"}


def exponent(currency: str) -> int:
    return 0 if currency.upper() in _ZERO_DECIMAL else 2


def to_minor(amount: str | int | Decimal, currency: str = "RUB") -> int:
    """'1 234,56' -> 123456. Бросает ValueError на мусоре."""
    if isinstance(amount, int):
        value = Decimal(amount)
    elif isinstance(amount, Decimal):
        value = amount
    else:
        cleaned = str(amount).strip().replace(" ", "").replace(" ", "").replace(",", ".")
        if not cleaned:
            raise ValueError("пустая сумма")
        try:
            value = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"некорректная сумма: {amount!r}") from exc

    factor = Decimal(10) ** exponent(currency)
    return int((value * factor).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_major(minor: int, currency: str = "RUB") -> Decimal:
    return Decimal(minor) / (Decimal(10) ** exponent(currency))


def format_amount(minor: int, currency: str = "RUB", *, sign: bool = False) -> str:
    """123456 -> '1 234.56'. Для отображения в боте."""
    digits = exponent(currency)
    negative = minor < 0
    value = abs(minor)
    whole, frac = divmod(value, 10**digits) if digits else (value, 0)
    # Неразрывный пробел: в Telegram число не рвётся по разрядам на новую строку
    grouped = f"{whole:,}".replace(",", " ")
    text = f"{grouped}.{frac:0{digits}d}" if digits else grouped
    if negative:
        return f"-{text}"
    return f"+{text}" if sign else text


def split_evenly(minor: int, parts: int) -> list[int]:
    """Делит сумму без потери копеек: остаток раскидывается по первым долям."""
    if parts <= 0:
        raise ValueError("parts must be positive")
    base, remainder = divmod(abs(minor), parts)
    shares = [base + (1 if i < remainder else 0) for i in range(parts)]
    return [-s for s in shares] if minor < 0 else shares
