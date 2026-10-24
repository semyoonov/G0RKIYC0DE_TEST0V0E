from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from app.core.exceptions import AssistantError
from app.core.logger import get_logger
from app.domain.enums import Platform
from app.interfaces.linking import display_name_of, app_text, identity_for, link_code_text

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.services.auth.service import AuthService

router = Router(name="telegram_link")
log = get_logger(__name__)

LINK_ERROR_TEXT = "Не удалось создать код привязки, попробуйте ещё раз."
APP_UNAVAILABLE_TEXT = "Публичный адрес приложения ещё не настроен."


def mini_app_url(settings: Settings, code: str | None = None) -> str | None:
    link = settings.mini_app_link(Platform.TELEGRAM, code)
    if link and link.startswith("https://"):
        return link
    return None


@router.message(Command("link"))
async def handle_link(message: Message, auth: AuthService, settings: Settings) -> None:
    if message.from_user is None:
        return
    user = message.from_user
    identity = identity_for(
        Platform.TELEGRAM,
        user.id,
        display_name_of(user.first_name, user.last_name) or (f"@{user.username}" if user.username else None),
    )
    try:
        code = await auth.issue_link_code(identity)
    except AssistantError:
        log.exception("telegram: link code request failed for user %s", user.id)
        await message.answer(LINK_ERROR_TEXT)
        return
    markup: InlineKeyboardMarkup | None = None
    url = mini_app_url(settings, code["code"])
    if url:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Открыть приложение", web_app=WebAppInfo(url=url))]]
        )
    await message.answer(link_code_text(settings, code["code"]), reply_markup=markup)


@router.message(Command("app"))
async def handle_app(message: Message, settings: Settings) -> None:
    if message.from_user is None:
        return
    url = mini_app_url(settings)
    if url is None:
        await message.answer(APP_UNAVAILABLE_TEXT)
        return
    markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть приложение", web_app=WebAppInfo(url=url))]]
    )
    await message.answer(app_text(settings), reply_markup=markup)
