from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from app.config import settings
from app.models import Category


def main_menu() -> ReplyKeyboardMarkup:
    """Постоянная клавиатура: кнопка Mini App плюс две частые команды."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Открыть", web_app=WebAppInfo(url=settings.public_url))],
            [KeyboardButton(text="📊 За месяц"), KeyboardButton(text="🏦 Баланс")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def open_app_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть приложение", web_app=WebAppInfo(url=settings.public_url)
                )
            ]
        ]
    )


def entry_actions(tx_id: str, categories: list[Category]) -> InlineKeyboardMarkup:
    """Кнопки под карточкой добавленной операции: сменить категорию или удалить."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for category in categories[:6]:
        label = f"{category.icon} {category.name}".strip()
        row.append(InlineKeyboardButton(text=label, callback_data=f"cat:{tx_id}:{category.id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{tx_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
