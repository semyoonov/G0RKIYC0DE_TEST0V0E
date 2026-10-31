from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from app.interfaces.linking import app_text

if TYPE_CHECKING:
    from app.core.config import Settings

router = Router(name="telegram_app")

APP_UNAVAILABLE_TEXT = "Публичный адрес приложения ещё не настроен."


def web_app_button(settings: Settings, text: str = "Открыть приложение") -> InlineKeyboardButton | None:
    base = settings.mini_app_base_url.rstrip("/")
    if not base or not base.startswith(("http://", "https://")):
        return None
    url = f"{base}/"
    if url.startswith("https://"):
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))
    return InlineKeyboardButton(text=text, url=url)


@router.message(Command("app"))
async def handle_app(message: Message, settings: Settings) -> None:
    if message.from_user is None:
        return
    button = web_app_button(settings, text="Открыть приложение")
    if button is None:
        await message.answer(APP_UNAVAILABLE_TEXT)
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[[button]])
    await message.answer(app_text(settings), reply_markup=markup)
