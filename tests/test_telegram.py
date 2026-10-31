from __future__ import annotations

import io
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Dispatcher
from aiogram.exceptions import TelegramBadRequest

from app.core.config import Settings
from app.core.exceptions import AssistantError
from app.domain.enums import EventStatus, EventType, Platform
from app.domain.models import AssistantResponse, EventRead
from app.interfaces.cards import DONE_BUTTON_LIMIT, cards_html
from app.interfaces.telegram.bot import BOT_COMMANDS, create_dispatcher
from app.interfaces.telegram.handlers import common, mini_app, text, voice
from app.interfaces.telegram.keyboards import (
    HELP_BUTTON,
    QUICK_ACTIONS,
    QUICK_TODAY,
    QUICK_TOMORROW,
    QUICK_WEEK,
    cards_inline_keyboard,
    main_keyboard,
)

MOSCOW = ZoneInfo("Europe/Moscow")
UTC = timezone.utc
CREATED_AT = datetime(2025, 3, 1, 9, 0, tzinfo=UTC)
STARTED_AT = datetime(2021, 5, 14, 7, 30, tzinfo=UTC)


def make_event(
    event_id: int = 1,
    *,
    event_type: EventType = EventType.MEETING,
    title: str = "Созвон с командой",
    starts_at: datetime | None = None,
    status: EventStatus = EventStatus.PENDING,
) -> EventRead:
    return EventRead(
        id=event_id,
        user_id=1,
        type=event_type,
        title=title,
        starts_at=starts_at,
        status=status,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


class FakeBot:
    def __init__(self, download: bytes = b"OGG-BYTES") -> None:
        self.chat_actions: list[tuple[int, str]] = []
        self.voices: list[dict[str, Any]] = []
        self._download = download

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        self.chat_actions.append((chat_id, action))

    async def send_voice(self, chat_id: int, voice: Any) -> None:
        self.voices.append({"chat_id": chat_id, "voice": voice})

    async def download(self, file: Any) -> io.BytesIO:
        return io.BytesIO(self._download)


class FakeMessage:
    def __init__(
        self,
        *,
        text: str | None = None,
        voice: Any | None = None,
        user_id: int = 42,
        bot: FakeBot | None = None,
    ) -> None:
        self.text = text
        self.voice = voice
        self.from_user = SimpleNamespace(id=user_id)
        self.chat = SimpleNamespace(id=user_id)
        self.bot = bot or FakeBot()
        self.answers: list[dict[str, Any]] = []
        self.edits: list[dict[str, Any]] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append({"text": text, **kwargs})


class RejectingEditMessage(FakeMessage):
    async def edit_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append({"text": text, **kwargs})
        if kwargs.get("parse_mode") == "HTML":
            raise TelegramBadRequest(method=None, message="Bad Request: message can't be edited")  # type: ignore[arg-type]


class FakeCallback:
    def __init__(self, data: str, *, user_id: int = 42, message: FakeMessage | None = None) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = message
        self.answers: list[dict[str, Any]] = []

    async def answer(self, text: str | None = None, **kwargs: Any) -> None:
        self.answers.append({"text": text, **kwargs})


class StubAssistant:
    def __init__(
        self,
        response: AssistantResponse | None = None,
        *,
        status_event: EventRead | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or AssistantResponse(text="Готово.")
        self.status_event = status_event
        self.error = error
        self.text_calls: list[tuple[Platform, str, str, bool]] = []
        self.voice_calls: list[tuple[Platform, str, bytes, str | None, bool]] = []
        self.status_calls: list[tuple[Platform, str, int, EventStatus]] = []

    async def handle_text(
        self,
        platform: Platform,
        external_user_id: str,
        text: str,
        *,
        speak: bool = False,
    ) -> AssistantResponse:
        self.text_calls.append((platform, external_user_id, text, speak))
        if self.error is not None:
            raise self.error
        return self.response

    async def handle_voice(
        self,
        platform: Platform,
        external_user_id: str,
        audio: bytes,
        *,
        source_format: str | None = None,
        speak: bool = True,
    ) -> AssistantResponse:
        self.voice_calls.append((platform, external_user_id, audio, source_format, speak))
        if self.error is not None:
            raise self.error
        return self.response

    async def set_event_status(
        self,
        platform: Platform,
        external_user_id: str,
        event_id: int,
        status: EventStatus,
    ) -> EventRead:
        self.status_calls.append((platform, external_user_id, event_id, status))
        if self.error is not None:
            raise self.error
        assert self.status_event is not None
        return self.status_event


def test_quick_actions_texts() -> None:
    assert QUICK_ACTIONS == (
        "Что у меня сегодня?",
        "Что на завтра?",
        "Что на этой неделе?",
    )
    assert QUICK_ACTIONS == (QUICK_TODAY, QUICK_TOMORROW, QUICK_WEEK)


def test_main_keyboard_layout() -> None:
    keyboard = main_keyboard()

    assert keyboard.resize_keyboard is True
    assert keyboard.is_persistent is True
    rows = [[button.text for button in row] for row in keyboard.keyboard]
    assert rows == [[QUICK_TODAY], [QUICK_TOMORROW], [QUICK_WEEK], [HELP_BUTTON]]


def test_cards_inline_keyboard_uses_pending_events() -> None:
    events = [make_event(index, title=f"Задача {index}") for index in range(1, 8)]

    keyboard = cards_inline_keyboard(events)

    assert keyboard is not None
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert len(buttons) == DONE_BUTTON_LIMIT
    assert [button.text for button in buttons] == ["✅ Выполнено"] * DONE_BUTTON_LIMIT
    assert [button.callback_data for button in buttons] == [f"event:done:{index}" for index in range(1, 6)]


def test_cards_inline_keyboard_skips_done_events() -> None:
    done = make_event(1, status=EventStatus.DONE)
    pending = make_event(2, status=EventStatus.PENDING)

    keyboard = cards_inline_keyboard([done, pending])

    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 1
    assert keyboard.inline_keyboard[0][0].callback_data == "event:done:2"


def test_cards_inline_keyboard_empty() -> None:
    assert cards_inline_keyboard([]) is None
    assert cards_inline_keyboard([make_event(1, status=EventStatus.DONE)]) is None


def test_dispatcher_includes_routers_in_order() -> None:
    dispatcher = create_dispatcher()

    assert isinstance(dispatcher, Dispatcher)
    assert [router.name for router in dispatcher.sub_routers] == [
        "telegram_common",
        "telegram_app",
        "telegram_text",
        "telegram_voice",
    ]
    assert dispatcher.sub_routers == [common.router, mini_app.router, text.router, voice.router]
    for router in (common.router, mini_app.router, text.router, voice.router):
        assert router.message.handlers
    assert text.router.callback_query.handlers


def test_common_router_registers_required_handlers() -> None:
    names = {handler.callback.__name__ for handler in common.router.message.handlers}

    assert {
        "handle_start",
        "handle_help",
        "handle_today",
        "handle_tomorrow",
        "handle_week",
        "handle_unknown_command",
        "handle_unsupported",
    } <= names


def test_period_queries_match_assistant_contract() -> None:
    assert common.TODAY_QUERY == "Что у меня сегодня?"
    assert common.TOMORROW_QUERY == "Какие задачи у меня на завтра?"
    assert common.WEEK_QUERY == "Что запланировано на эту неделю?"


def test_bot_commands() -> None:
    assert [command.command for command in BOT_COMMANDS] == [
        "start",
        "help",
        "today",
        "tomorrow",
        "week",
        "app",
    ]


def test_voice_limits() -> None:
    assert voice.VOICE_MAX_DURATION_SECONDS == 120
    assert voice.VOICE_MAX_BYTES == 20 * 1024 * 1024


def test_settings_timezone_is_moscow(settings: Settings) -> None:
    assert settings.tz == MOSCOW


async def test_text_handler_sends_plain_answer_then_html_card(settings: Settings) -> None:
    event = make_event(1, starts_at=STARTED_AT)
    assistant = StubAssistant(
        AssistantResponse(text="Встреча создана.", events=[event], intent="create_meeting")
    )
    message = FakeMessage(text="Встреча с командой завтра в 10")

    await text.handle_text_message(message, assistant=assistant, settings=settings)

    assert assistant.text_calls == [(Platform.TELEGRAM, "42", message.text, False)]
    assert len(message.answers) == 2
    answer, card = message.answers
    assert answer == {"text": "Встреча создана."}
    assert card["parse_mode"] == "HTML"
    assert card["text"] == cards_html([event], MOSCOW, "Создано")
    assert card["reply_markup"].inline_keyboard[0][0].callback_data == "event:done:1"


async def test_text_handler_listing_card_has_no_action_line(settings: Settings) -> None:
    event = make_event(1, starts_at=STARTED_AT)
    assistant = StubAssistant(AssistantResponse(text="На завтра одна встреча.", events=[event]))
    message = FakeMessage(text="Что на завтра?")

    await text.handle_text_message(message, assistant=assistant, settings=settings)

    assert len(message.answers) == 2
    card = message.answers[1]
    assert card["parse_mode"] == "HTML"
    assert card["text"] == cards_html([event], MOSCOW)
    assert not card["text"].startswith("<b>Создано")


async def test_text_handler_without_events_sends_only_answer(settings: Settings) -> None:
    assistant = StubAssistant(AssistantResponse(text="Уточните дату."))
    message = FakeMessage(text="Напомни позвонить")

    await text.handle_text_message(message, assistant=assistant, settings=settings)

    assert message.answers == [{"text": "Уточните дату."}]


async def test_text_handler_empty_answer_text_sends_only_card(settings: Settings) -> None:
    event = make_event(1, event_type=EventType.TASK, title="Позвонить в банк")
    assistant = StubAssistant(AssistantResponse(text="   ", events=[event], intent="create_task"))
    message = FakeMessage(text="Напомни позвонить в банк")

    await text.handle_text_message(message, assistant=assistant, settings=settings)

    assert len(message.answers) == 1
    assert message.answers[0]["parse_mode"] == "HTML"
    assert message.answers[0]["text"] == cards_html([event], MOSCOW, "Создано")


async def test_text_handler_error(settings: Settings) -> None:
    assistant = StubAssistant(error=AssistantError("boom"))
    message = FakeMessage(text="Встреча завтра")

    await text.handle_text_message(message, assistant=assistant, settings=settings)

    assert message.answers == [{"text": text.ERROR_TEXT}]


async def test_period_command_sends_plain_listing_without_card(settings: Settings) -> None:
    event = make_event(1, starts_at=STARTED_AT)
    assistant = StubAssistant(AssistantResponse(text="Сегодня встреча в 10:30.", events=[event]))
    message = FakeMessage(text="/today")

    await common.handle_today(message, assistant=assistant, settings=settings)

    assert len(message.answers) == 1
    assert message.answers[0] == {"text": "Сегодня встреча в 10:30."}
    assert message.bot.chat_actions == [(42, "typing")]


async def test_voice_handler_sends_text_and_card_without_voice(settings: Settings) -> None:
    event = make_event(1, event_type=EventType.TASK, title="Позвонить в банк")
    assistant = StubAssistant(
        AssistantResponse(
            text="Задача создана.",
            events=[event],
            intent="create_task",
            audio=b"AUDIO-BYTES",
            audio_format="opus",
        )
    )
    bot = FakeBot()
    message = FakeMessage(voice=SimpleNamespace(duration=5, file_size=1024), bot=bot)

    await voice.handle_voice_message(message, assistant=assistant, settings=settings)

    assert assistant.voice_calls == [(Platform.TELEGRAM, "42", b"OGG-BYTES", "ogg", False)]
    assert bot.voices == []
    assert len(message.answers) == 2
    answer, card = message.answers
    assert answer == {"text": "Задача создана."}
    assert card["parse_mode"] == "HTML"
    assert card["text"] == cards_html([event], MOSCOW, "Создано")


async def test_voice_handler_without_events_sends_only_answer(settings: Settings) -> None:
    assistant = StubAssistant(AssistantResponse(text="Расшифровал."))
    message = FakeMessage(voice=SimpleNamespace(duration=5, file_size=1024))

    await voice.handle_voice_message(message, assistant=assistant, settings=settings)

    assert message.answers == [{"text": "Расшифровал."}]


async def test_voice_handler_rejects_long_voice(settings: Settings) -> None:
    assistant = StubAssistant()
    message = FakeMessage(
        voice=SimpleNamespace(duration=voice.VOICE_MAX_DURATION_SECONDS + 1, file_size=1)
    )

    await voice.handle_voice_message(message, assistant=assistant, settings=settings)

    assert assistant.voice_calls == []
    assert message.answers == [{"text": voice.VOICE_TOO_LONG_TEXT}]


async def test_done_callback_edits_card_and_removes_button(settings: Settings) -> None:
    done_event = make_event(5, starts_at=STARTED_AT, status=EventStatus.DONE)
    assistant = StubAssistant(status_event=done_event)
    message = FakeMessage()
    callback = FakeCallback("event:done:5", message=message)

    await text.handle_event_done(callback, assistant=assistant, settings=settings)

    assert assistant.status_calls == [(Platform.TELEGRAM, "42", 5, EventStatus.DONE)]
    assert callback.answers == [{"text": None}]
    assert len(message.edits) == 1
    edit = message.edits[0]
    assert edit["text"] == cards_html([done_event], MOSCOW, "Выполнено")
    assert edit["parse_mode"] == "HTML"
    assert edit["reply_markup"].inline_keyboard == []


async def test_done_callback_falls_back_to_plain_confirmation(settings: Settings) -> None:
    done_event = make_event(5, status=EventStatus.DONE)
    assistant = StubAssistant(status_event=done_event)
    message = RejectingEditMessage()
    callback = FakeCallback("event:done:5", message=message)

    await text.handle_event_done(callback, assistant=assistant, settings=settings)

    assert len(message.edits) == 2
    assert message.edits[1] == {"text": "Отмечено как выполнено: Созвон с командой"}


async def test_done_callback_ignores_malformed_payload(settings: Settings) -> None:
    assistant = StubAssistant()
    message = FakeMessage()
    callback = FakeCallback("event:done:not-a-number", message=message)

    await text.handle_event_done(callback, assistant=assistant, settings=settings)

    assert assistant.status_calls == []
    assert message.edits == []
    assert callback.answers == [{"text": text.ERROR_TEXT, "show_alert": True}]


async def test_done_callback_reports_assistant_error(settings: Settings) -> None:
    assistant = StubAssistant(error=AssistantError("boom"))
    message = FakeMessage()
    callback = FakeCallback("event:done:5", message=message)

    await text.handle_event_done(callback, assistant=assistant, settings=settings)

    assert assistant.status_calls == [(Platform.TELEGRAM, "42", 5, EventStatus.DONE)]
    assert message.edits == []
    assert callback.answers == [{"text": text.ERROR_TEXT, "show_alert": True}]


async def test_handle_start_greets_with_the_keyboard(settings: Settings) -> None:
    message = FakeMessage(user_id=42)

    await common.handle_start(message)

    assert len(message.answers) == 1
    assert "задачи, встречи и напоминания" in message.answers[0]["text"]
    assert message.answers[0]["reply_markup"] is not None
