import asyncio
import contextlib
import signal

import uvicorn

from aiogram import Bot

from app.ai.assistant import AssistantService
from app.ai.llm.gigachat_client import GigaChatClient
from app.ai.stt.audio_converter import AudioConverter
from app.ai.stt.vosk_stt import VoskSpeechRecognizer
from app.ai.tts.sber_tts import SberTextToSpeech
from app.core.config import Settings, get_settings
from app.core.exceptions import AssistantError
from app.core.logger import get_logger, setup_logging
from app.core.timeutils import format_datetime
from app.db.models.event import Event
from app.db.session import Database
from app.domain.enums import EVENT_TYPE_TITLES, Platform
from app.interfaces.max.bot import MaxBot, MaxClient
from app.interfaces.telegram.bot import run_telegram_bot
from app.interfaces.web.app import create_app
from app.interfaces.web.ws import StreamingFactory
from app.services.cache.redis_service import CacheService
from app.services.scheduler.reminder_service import ReminderService

log = get_logger(__name__)


def reminder_text(event: Event, settings: Settings) -> str:
    moment = event.starts_at or event.remind_at
    subject = EVENT_TYPE_TITLES[event.type]
    if moment is None:
        return f"Напоминание: {subject} «{event.title}»."
    return f"Напоминание: {subject} «{event.title}» — {format_datetime(moment, settings.tz)}."


class Application:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = Database(self.settings)
        self.cache = CacheService(
            self.settings.redis_url,
            enabled=self.settings.cache_enabled,
            ttl_seconds=self.settings.cache_ttl_seconds,
        )
        self.llm = GigaChatClient(self.settings) if self.settings.gigachat_enabled else None
        self.tts = SberTextToSpeech(self.settings) if self.settings.tts_enabled else None
        self.stt = VoskSpeechRecognizer(self.settings.vosk_model_path, self.settings.audio_sample_rate)
        self.converter = AudioConverter(
            self.settings.ffmpeg_binary,
            self.settings.audio_sample_rate,
            self.settings.audio_max_duration_seconds,
        )
        self.assistant = AssistantService(
            self.db.session_factory,
            self.settings,
            llm=self.llm,
            stt=self.stt,
            tts=self.tts,
            converter=self.converter,
            cache=self.cache,
        )
        self.reminders = ReminderService(
            self.db.session_factory,
            poll_interval_seconds=self.settings.reminder_poll_seconds,
            lookahead_seconds=self.settings.reminder_lookahead_seconds,
        )
        self.tasks: list[asyncio.Task[None]] = []
        self.server: uvicorn.Server | None = None
        self.max_bot: MaxBot | None = None
        self.telegram_reminder_bot: Bot | None = None
        self.max_reminder_client: MaxClient | None = None
        self._stopping = False

    async def start(self) -> None:
        if self.settings.auto_create_tables:
            await self.db.create_all()
        self._start_web()
        if self.settings.telegram_enabled:
            self.tasks.append(asyncio.create_task(self._run_telegram(), name="telegram-bot"))
        if self.settings.max_enabled:
            self.max_bot = MaxBot(self.assistant, self.settings)
            await self.max_bot.start()
        if self.settings.enable_scheduler:
            await self._register_reminder_notifiers()
            await self.reminders.start()
        try:
            if await self.stt.warmup():
                log.info("vosk model is loaded")
        except AssistantError as error:
            log.warning("vosk warmup failed: %s", error)
        log.info(
            "assistant is up: llm=%s tts=%s telegram=%s max=%s scheduler=%s",
            self.assistant.llm_enabled,
            self.settings.tts_enabled,
            self.settings.telegram_enabled,
            self.settings.max_enabled,
            self.settings.enable_scheduler,
        )
        if not self.assistant.llm_enabled:
            log.warning(
                "GigaChat is not configured: set GIGACHAT_CREDENTIALS, "
                "otherwise every request returns a setup hint"
            )

    async def stop(self) -> None:
        self._stopping = True
        if self.server is not None:
            self.server.should_exit = True
        await self.reminders.stop()
        if self.max_bot is not None:
            await self.max_bot.stop()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.assistant.close()
        if self.telegram_reminder_bot is not None:
            await self.telegram_reminder_bot.session.close()
        if self.max_reminder_client is not None:
            await self.max_reminder_client.close()
        await self.cache.close()
        await self.db.dispose()

    async def _run_telegram(self) -> None:
        delay = 5
        while not self._stopping:
            try:
                await run_telegram_bot(self.assistant, self.settings)
                return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - startup or polling failure must be retried, not hidden
                log.exception("telegram bot failed, restarting in %ss", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    def _streaming_factory(self) -> StreamingFactory:
        max_bytes = self.settings.audio_max_duration_seconds * self.settings.audio_sample_rate * 2
        return lambda: self.stt.open_stream(max_bytes=max_bytes)

    def _start_web(self) -> None:
        web_app = create_app(self.assistant, self.settings, streaming_factory=self._streaming_factory())
        config = uvicorn.Config(
            web_app,
            host=self.settings.web_host,
            port=self.settings.web_port,
            log_level=self.settings.log_level.lower(),
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.tasks.append(asyncio.create_task(self.server.serve(), name="web"))

    async def _register_reminder_notifiers(self) -> None:
        settings = self.settings
        if settings.telegram_enabled:
            bot = Bot(token=settings.telegram_bot_token)
            self.telegram_reminder_bot = bot

            async def notify_telegram(user, event: Event) -> None:
                await bot.send_message(chat_id=int(user.external_id), text=reminder_text(event, settings))

            self.reminders.register_notifier(Platform.TELEGRAM, notify_telegram)

        if settings.max_enabled:
            client = MaxClient(settings.max_api_base_url, settings.max_bot_token, verify=settings.tls_verify)
            self.max_reminder_client = client

            async def notify_max(user, event: Event) -> None:
                await client.send_text(user.external_id, reminder_text(event, settings))

            self.reminders.register_notifier(Platform.MAX, notify_max)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    application = Application(settings)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)
    await application.start()
    await stop_event.wait()
    log.info("shutting down")
    await application.stop()


if __name__ == "__main__":
    asyncio.run(main())
