from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from app.core.exceptions import AssistantError
from app.core.logger import get_logger
from app.domain.enums import Platform
from app.interfaces.linking import display_name_of, app_text, identity_for, link_code_text
from app.interfaces.telegram.keyboards import main_keyboard
from app.services.auth.service import LinkCodeError

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.services.auth.service import AuthService

router = Router(name="telegram_link")
log = get_logger(__name__)

LINK_ERROR_TEXT = "Не удалось создать код привязки, попробуйте ещё раз."
APP_UNAVAILABLE_TEXT = "Публичный адрес приложения ещё не настроен."


def web_app_button(settings: Settings, text: str = "Открыть приложение", code: str | None = None) -> InlineKeyboardButton | None:
    base = settings.mini_app_base_url.rstrip("/")
    if not base or not base.startswith(("http://", "https://")):
        return None
    url = f"{base}/?link={code}" if code else f"{base}/"
    if url.startswith("https://"):
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))
    return InlineKeyboardButton(text=text, url=url)


@router.message(Command("link"))
async def handle_link(
    message: Message,
    auth: AuthService,
    settings: Settings,
    command: CommandObject | None = None,
) -> None:
    if message.from_user is None:
        return
    user = message.from_user
    first_name = getattr(user, "first_name", None)
    last_name = getattr(user, "last_name", None)
    username = getattr(user, "username", None)
    identity = identity_for(
        Platform.TELEGRAM,
        user.id,
        display_name_of(first_name, last_name) or (f"@{username}" if username else None),
    )
    code_arg = (command.args or "").strip() if command else ""
    if code_arg:
        try:
            await auth.redeem(identity, code_arg)
            log.info("telegram: redeemed link code %s for user %s via /link", code_arg, user.id)
            await message.answer(
                "✅ Аккаунт успешно привязан!\n"
                "Теперь ваши задачи, встречи и напоминания синхронизированы между Telegram и веб-версией.",
                reply_markup=main_keyboard(),
            )
            return
        except LinkCodeError as exc:
            await message.answer(
                f"❌ Не удалось привязать аккаунт: {exc}.\n\n"
                "Проверьте код или получите новый в веб-приложении.",
                reply_markup=main_keyboard(),
            )
            return
        except Exception:
            log.exception("telegram: link redeem failed for user %s", user.id)
            await message.answer(
                "❌ Не удалось привязать аккаунт, попробуйте ещё раз.",
                reply_markup=main_keyboard(),
            )
            return

    try:
        code = await auth.issue_link_code(identity)
    except AssistantError:
        log.exception("telegram: link code request failed for user %s", user.id)
        await message.answer(LINK_ERROR_TEXT)
        return

    markup: InlineKeyboardMarkup | None = None
    btn = web_app_button(settings, text="Открыть веб-приложение", code=code["code"])
    if btn:
        markup = InlineKeyboardMarkup(inline_keyboard=[[btn]])
    await message.answer(link_code_text(settings, code["code"]), reply_markup=markup)


@router.message(Command("app"))
async def handle_app(message: Message, settings: Settings) -> None:
    if message.from_user is None:
        return
    btn = web_app_button(settings, text="Открыть приложение")
    if btn is None:
        await message.answer(APP_UNAVAILABLE_TEXT)
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[[btn]])
    await message.answer(app_text(settings), reply_markup=markup)
