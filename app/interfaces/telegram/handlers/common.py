from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.core.exceptions import AssistantError
from app.core.logger import get_logger
from app.domain.enums import Platform
from app.interfaces.telegram.handlers.text import ERROR_TEXT
from app.interfaces.telegram.keyboards import (
    HELP_BUTTON,
    QUICK_TODAY,
    main_keyboard,
)

if TYPE_CHECKING:
    from app.ai.assistant import AssistantService
    from app.core.config import Settings

router = Router(name="telegram_common")
logger = get_logger(__name__)

TODAY_QUERY = QUICK_TODAY
TOMORROW_QUERY = "Какие задачи у меня на завтра?"
WEEK_QUERY = "Что запланировано на эту неделю?"

START_TEXT = (
    "Привет! Я веду задачи, встречи и напоминания и напоминаю о сроках.\n"
    "Напишите или запишите голосовое — например: «Завтра в 10 встреча с командой»."
)

HELP_TEXT = (
    "Что я умею:\n"
    "— задачи и напоминания: «Напомни завтра в 9 позвонить в банк»\n"
    "— встречи: «Встреча с Аней в пятницу в 15:00»\n"
    "— планы на период: «Что у меня на этой неделе?»\n"
    "— старые события: «Какие встречи были в прошлом месяце?»\n\n"
    "Можно писать текстом или отправлять голосовые — я распознаю речь и отвечу текстом."
)

UNKNOWN_COMMAND_TEXT = "Не знаю такую команду. Откройте /help, чтобы увидеть, что я умею."
UNSUPPORTED_TEXT = "Такие сообщения я пока не понимаю. Напишите текстом, запишите голосовое или откройте /help."


async def _reply_period(
    message: Message,
    assistant: AssistantService,
    settings: Settings,
    query: str,
) -> None:
    if message.from_user is None:
        return
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        response = await assistant.handle_text(
            Platform.TELEGRAM,
            str(message.from_user.id),
            query,
            speak=False,
        )
    except AssistantError:
        logger.exception("telegram: period request failed for user %s", message.from_user.id)
        await message.answer(ERROR_TEXT)
        return
    await message.answer(response.text.strip())


@router.message(Command("start"))
async def handle_start(message: Message) -> None:
    await message.answer(START_TEXT, reply_markup=main_keyboard())


@router.message(Command("help"))
async def handle_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_keyboard())


@router.message(F.text.lower() == HELP_BUTTON.lower())
async def handle_help_button(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=main_keyboard())


@router.message(Command("today"))
async def handle_today(message: Message, assistant: AssistantService, settings: Settings) -> None:
    await _reply_period(message, assistant, settings, TODAY_QUERY)


@router.message(Command("tomorrow"))
async def handle_tomorrow(message: Message, assistant: AssistantService, settings: Settings) -> None:
    await _reply_period(message, assistant, settings, TOMORROW_QUERY)


@router.message(Command("week"))
async def handle_week(message: Message, assistant: AssistantService, settings: Settings) -> None:
    await _reply_period(message, assistant, settings, WEEK_QUERY)


@router.message(F.text.startswith("/"))
async def handle_unknown_command(message: Message) -> None:
    await message.answer(UNKNOWN_COMMAND_TEXT, reply_markup=main_keyboard())


@router.message(~F.text, ~F.voice)
async def handle_unsupported(message: Message) -> None:
    await message.answer(UNSUPPORTED_TEXT, reply_markup=main_keyboard())
