from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.types import BufferedInputFile, Message

from app.core.exceptions import AssistantError
from app.core.logger import get_logger
from app.domain.enums import Platform
from app.interfaces.telegram.handlers.text import ERROR_TEXT, send_answer

if TYPE_CHECKING:
    from app.ai.assistant import AssistantService
    from app.core.config import Settings

router = Router(name="telegram_voice")
logger = get_logger(__name__)

VOICE_MAX_DURATION_SECONDS = 120
VOICE_MAX_BYTES = 20 * 1024 * 1024

VOICE_TOO_LONG_TEXT = "Слишком длинное голосовое: максимум 2 минуты. Запишите короче или напишите текстом."
VOICE_TOO_LARGE_TEXT = "Слишком большой файл: максимум 20 МБ."
VOICE_EMPTY_TEXT = "Не удалось прочитать голосовое, попробуйте ещё раз."


@router.message(F.voice)
async def handle_voice_message(
    message: Message,
    assistant: AssistantService,
    settings: Settings,
) -> None:
    voice = message.voice
    if message.from_user is None or voice is None:
        return
    if voice.duration > VOICE_MAX_DURATION_SECONDS:
        await message.answer(VOICE_TOO_LONG_TEXT)
        return
    if (voice.file_size or 0) > VOICE_MAX_BYTES:
        await message.answer(VOICE_TOO_LARGE_TEXT)
        return

    source = await message.bot.download(voice)
    audio = source.read() if source is not None else b""
    if not audio:
        await message.answer(VOICE_EMPTY_TEXT)
        return
    if len(audio) > VOICE_MAX_BYTES:
        await message.answer(VOICE_TOO_LARGE_TEXT)
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        response = await assistant.handle_voice(
            Platform.TELEGRAM,
            str(message.from_user.id),
            audio,
            source_format="ogg",
            speak=True,
        )
    except AssistantError:
        logger.exception("telegram: voice request failed for user %s", message.from_user.id)
        await message.answer(ERROR_TEXT)
        return

    if response.audio is not None:
        await message.bot.send_voice(
            chat_id=message.chat.id,
            voice=BufferedInputFile(response.audio, filename="answer.ogg"),
        )
    await send_answer(message, response, settings.tz)
