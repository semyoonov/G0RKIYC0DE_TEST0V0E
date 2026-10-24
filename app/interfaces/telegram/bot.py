from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from app.core.logger import get_logger
from app.interfaces.telegram.handlers import common, link, text, voice

if TYPE_CHECKING:
    from app.ai.assistant import AssistantService
    from app.core.config import Settings
    from app.services.auth.service import AuthService

logger = get_logger(__name__)

BOT_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand(command="start", description="Начать работу"),
    BotCommand(command="help", description="Примеры запросов"),
    BotCommand(command="today", description="Планы на сегодня"),
    BotCommand(command="tomorrow", description="Планы на завтра"),
    BotCommand(command="week", description="Планы на неделю"),
    BotCommand(command="link", description="Код привязки аккаунта"),
    BotCommand(command="app", description="Открыть приложение"),
)


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(common.router)
    dispatcher.include_router(link.router)
    dispatcher.include_router(text.router)
    dispatcher.include_router(voice.router)
    return dispatcher


async def run_telegram_bot(assistant: AssistantService, settings: Settings, auth: AuthService | None = None) -> None:
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=None),
    )
    dispatcher = create_dispatcher()
    try:
        await bot.set_my_commands(list(BOT_COMMANDS))
        logger.info("telegram: polling started")
        await dispatcher.start_polling(
            bot,
            assistant=assistant,
            settings=settings,
            auth=auth,
            handle_signals=False,
        )
    finally:
        await bot.session.close()
        logger.info("telegram: polling stopped")
