from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.domain.models import EventRead
from app.interfaces.cards import DONE_CALLBACK_PREFIX, done_button, pending_events

QUICK_TODAY = "Что у меня сегодня?"
QUICK_TOMORROW = "Что на завтра?"
QUICK_WEEK = "Что на этой неделе?"
QUICK_ACTIONS: tuple[str, ...] = (QUICK_TODAY, QUICK_TOMORROW, QUICK_WEEK)

HELP_BUTTON = "Помощь"

__all__ = [
    "DONE_CALLBACK_PREFIX",
    "HELP_BUTTON",
    "QUICK_ACTIONS",
    "QUICK_TODAY",
    "QUICK_TOMORROW",
    "QUICK_WEEK",
    "cards_inline_keyboard",
    "help_keyboard",
    "main_keyboard",
]


def main_keyboard() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=action)] for action in QUICK_ACTIONS]
    rows.append([KeyboardButton(text=HELP_BUTTON)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)


def help_keyboard() -> ReplyKeyboardMarkup:
    return main_keyboard()


def cards_inline_keyboard(events: Sequence[EventRead]) -> InlineKeyboardMarkup | None:
    """Кнопки «Готово» для записей, ещё ждущих действия."""
    rows: list[list[InlineKeyboardButton]] = []
    for event in pending_events(events):
        button = done_button(event)
        if button is None:
            continue
        text, callback_data = button
        rows.append([InlineKeyboardButton(text=text, callback_data=callback_data)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
