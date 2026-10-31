from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.core.exceptions import AssistantError
from app.core.logger import get_logger
from app.domain.enums import EventStatus, Platform
from app.domain.models import AssistantResponse, EventRead
from app.interfaces.cards import (
    DONE_CALLBACK_PREFIX,
    action_label,
    cards_html,
    parse_done_callback,
)
from app.interfaces.telegram.keyboards import cards_inline_keyboard

if TYPE_CHECKING:
    from app.ai.assistant import AssistantService
    from app.core.config import Settings

router = Router(name="telegram_text")
logger = get_logger(__name__)

ERROR_TEXT = "Не получилось обработать запрос, попробуйте ещё раз."
DONE_CONFIRMATION_TEXT = "Отмечено как выполнено: {title}"


async def send_answer(message: Message, response: AssistantResponse, tz: ZoneInfo) -> None:
    """Сначала фраза ассистента отдельным сообщением, затем карточки."""
    text = response.text.strip()
    if text:
        await message.answer(text)
    await send_cards(message, response.events, tz, action_label(response.intent))


async def send_cards(
    message: Message,
    events: Sequence[EventRead],
    tz: ZoneInfo,
    action: str | None = None,
) -> None:
    if not events:
        return
    await message.answer(
        cards_html(events, tz, action),
        parse_mode="HTML",
        reply_markup=cards_inline_keyboard(events),
    )


async def _typing(message: Message) -> None:
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")


@router.message(F.text, ~F.text.startswith("/"))
async def handle_text_message(
    message: Message,
    assistant: AssistantService,
    settings: Settings,
) -> None:
    if message.from_user is None or not message.text:
        return
    await _typing(message)
    try:
        response = await assistant.handle_text(
            Platform.TELEGRAM,
            str(message.from_user.id),
            message.text,
            speak=False,
        )
    except AssistantError:
        logger.exception("telegram: text request failed for user %s", message.from_user.id)
        await message.answer(ERROR_TEXT)
        return
    await send_answer(message, response, settings.tz)


async def _edit_to_done_card(message: Message, event: EventRead, tz: ZoneInfo) -> None:
    try:
        await message.edit_text(
            cards_html([event], tz, action_label("complete_event")),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),
        )
        return
    except TelegramBadRequest:
        logger.warning("telegram: card edit rejected for event %s", event.id, exc_info=True)
    try:
        await message.edit_text(DONE_CONFIRMATION_TEXT.format(title=event.title))
    except TelegramAPIError:
        logger.warning("telegram: done confirmation rejected for event %s", event.id, exc_info=True)


@router.callback_query(F.data.startswith(DONE_CALLBACK_PREFIX))
async def handle_event_done(
    callback: CallbackQuery,
    assistant: AssistantService,
    settings: Settings,
) -> None:
    event_id = parse_done_callback(callback.data)
    if event_id is None:
        await callback.answer(ERROR_TEXT, show_alert=True)
        return
    try:
        event = await assistant.set_event_status(
            Platform.TELEGRAM,
            str(callback.from_user.id),
            event_id,
            EventStatus.DONE,
        )
    except AssistantError:
        logger.exception("telegram: marking event %s as done failed", event_id)
        await callback.answer(ERROR_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await _edit_to_done_card(callback.message, event, settings.tz)
