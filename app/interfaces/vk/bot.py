from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from vkbottle import Bot, GroupEventType
from vkbottle.bot import BotLabeler, Message

from app.core.logger import get_logger
from app.interfaces.vk.handlers import handle_callback_payload, handle_message

if TYPE_CHECKING:
    from app.ai.assistant import AssistantService
    from app.core.config import Settings

log = get_logger(__name__)

_RESTART_DELAYS = (5, 15, 30, 60)


class VkBot:
    """Бот ВК на long polling поверх сервиса ассистента."""

    def __init__(
        self,
        assistant: AssistantService,
        settings: Settings,
    ) -> None:
        self._assistant = assistant
        self._settings = settings
        self._bot: Bot | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if not self._settings.vk_enabled:
            log.warning("VK bot is disabled: vk_bot_token is not configured")
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="vk-polling")
        log.info("VK bot polling started")

    async def stop(self) -> None:
        self._stopping = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._bot is not None:
            client = getattr(self._bot.api, "http_client", None)
            closer = getattr(client, "close", None)
            if closer is not None:
                await closer()
        log.info("VK bot stopped")

    async def send_text(self, user_id: str | int, text: str) -> None:
        if self._bot is None:
            raise RuntimeError("VK bot is not running")
        await self._bot.api.messages.send(
            user_id=int(user_id),
            random_id=_random_id(),
            message=text[:4000],
            dont_parse_links=1,
        )

    async def _run(self) -> None:
        delay_index = 0
        while not self._stopping:
            try:
                await self._poll()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                delay = _RESTART_DELAYS[min(delay_index, len(_RESTART_DELAYS) - 1)]
                delay_index += 1
                log.exception("VK bot failed, restarting in %ss", delay)
                await asyncio.sleep(delay)

    async def _poll(self) -> None:
        labeler = BotLabeler()
        bot = Bot(token=self._settings.vk_bot_token, labeler=labeler)
        self._bot = bot

        @labeler.message()
        async def _on_message(message: Message) -> None:
            await handle_message(message, bot.api, self._assistant, self._settings)

        @labeler.raw_event(GroupEventType.MESSAGE_EVENT)
        async def _on_message_event(event: dict[str, Any]) -> None:
            payload = event.get("object") or {}
            user_id = payload.get("user_id")
            peer_id = payload.get("peer_id")
            if user_id is None or peer_id is None:
                return
            try:
                await handle_callback_payload(
                    payload.get("payload"),
                    bot.api,
                    self._assistant,
                    int(user_id),
                    int(peer_id),
                    payload.get("event_id"),
                )
            except Exception:
                log.exception("VK button handling failed")

        log.info("VK bot is polling")
        await bot.run_polling()


def _random_id() -> int:
    import secrets

    return secrets.randbelow(2**31 - 1)
