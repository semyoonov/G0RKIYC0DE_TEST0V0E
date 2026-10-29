from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import Settings
from app.domain.enums import EventStatus, EventType, Platform
from app.domain.models import AssistantResponse, EventRead
from app.interfaces.vk import handlers
from app.interfaces.vk.handlers import (
    ERROR_REPLY,
    GREETING,
    _event_id_from_payload,
    handle_callback_payload,
    handle_message,
)
from datetime import datetime, timezone

FIXED_TIME = datetime(2025, 5, 20, 9, 30, tzinfo=timezone.utc)


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "database_url": "sqlite+aiosqlite://",
        "cache_enabled": False,
        "auto_create_tables": False,
        "sber_tts_credentials": "",
        "local_tts_enabled": False,
        "vk_bot_token": "vk-token",
        "vk_bot_group_id": 242413551,
        "web_public_url": "https://assistant.test",
        "timezone": "Europe/Moscow",
    }
    values.update(overrides)
    return Settings(**values)


def make_event(event_id: int = 5) -> EventRead:
    return EventRead(
        id=event_id,
        user_id=1,
        type=EventType.TASK,
        title="Позвонить в банк",
        description=None,
        starts_at=FIXED_TIME,
        remind_at=None,
        status=EventStatus.PENDING,
        source=Platform.VK,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )


class FakeMessages:
    def __init__(self, log: list[dict[str, Any]]) -> None:
        self._log = log
        self.answers: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> dict[str, Any]:
        self._log.append(kwargs)
        return {"response": 1}

    async def send_message_event_answer(self, **kwargs: Any) -> dict[str, Any]:
        self.answers.append(kwargs)
        return {"response": 1}


class FakeApi:
    def __init__(self) -> None:
        self.log: list[dict[str, Any]] = []
        self.messages = FakeMessages(self.log)


class FakeAssistant:
    def __init__(self) -> None:
        self.text_calls: list[tuple[Platform, str, str]] = []
        self.voice_calls: list[tuple[Platform, str, bytes, str | None, bool]] = []
        self.status_calls: list[tuple[Platform, str, int, EventStatus]] = []

    async def handle_text(self, platform: Platform, external_user_id: str, text: str) -> AssistantResponse:
        self.text_calls.append((platform, external_user_id, text))
        return AssistantResponse(text=f"Ответ: {text}", events=[make_event()])

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
        return AssistantResponse(text="Голосовой ответ", audio=b"OPUS")

    async def set_event_status(
        self,
        platform: Platform,
        external_user_id: str,
        event_id: int,
        status: EventStatus,
    ) -> EventRead:
        self.status_calls.append((platform, external_user_id, event_id, status))
        return make_event(event_id)


class FakeAuth:
    def __init__(self) -> None:
        self.identities: list[tuple[Platform, str]] = []

    async def issue_link_code(self, identity) -> dict[str, Any]:
        self.identities.append((identity.platform, identity.external_id))
        return {"code": "AB12CD"}


def make_message(text: str = "", attachments: list[Any] | None = None, user_id: int = 777) -> Any:
    return SimpleNamespace(from_id=user_id, peer_id=user_id, text=text, attachments=attachments or [])


async def test_start_replies_with_greeting_and_keyboard() -> None:
    api, assistant = FakeApi(), FakeAssistant()

    await handle_message(make_message("/start"), api, assistant, make_settings(), None)

    assert api.log[0]["message"] == GREETING
    assert api.log[0]["keyboard"]
    assert assistant.text_calls == []


async def test_text_goes_through_assistant() -> None:
    api, assistant = FakeApi(), FakeAssistant()

    await handle_message(make_message("Напомни завтра про отчёт"), api, assistant, make_settings(), None)

    assert assistant.text_calls == [(Platform.VK, "777", "Напомни завтра про отчёт")]
    assert api.log[0]["message"] == "Ответ: Напомни завтра про отчёт"
    assert api.log[0]["peer_id"] == 777


async def test_voice_attachment_is_transcribed(monkeypatch: pytest.MonkeyPatch) -> None:
    api, assistant = FakeApi(), FakeAssistant()
    audio = SimpleNamespace(link_ogg="https://example.test/voice.ogg", link_mp3=None)
    attachment = SimpleNamespace(type="audio_message", audio_message=audio, audio=None)

    async def fake_download(url: str) -> bytes:
        assert url == "https://example.test/voice.ogg"
        return b"OGGDATA"

    monkeypatch.setattr(handlers, "download_voice", fake_download)

    await handle_message(make_message("", [attachment]), api, assistant, make_settings(), None)

    assert assistant.voice_calls == [(Platform.VK, "777", b"OGGDATA", "ogg", False)]
    assert "attachment" not in api.log[0]


async def test_link_command_prints_code() -> None:
    api, assistant, auth = FakeApi(), FakeAssistant(), FakeAuth()

    await handle_message(make_message("/link"), api, assistant, make_settings(), auth)

    assert auth.identities == [(Platform.VK, "777")]
    assert "AB12CD" in api.log[0]["message"]


async def test_app_command_sends_the_mini_app_button() -> None:
    api, assistant = FakeApi(), FakeAssistant()

    await handle_message(
        make_message("/app"),
        api,
        assistant,
        make_settings(vk_mini_app_id=54852072),
        None,
    )

    assert "vk.com/app54852072" in api.log[0]["message"]
    assert "vk.com/app54852072" in api.log[0]["keyboard"]
    assert '"open_link"' in api.log[0]["keyboard"]


async def test_start_keyboard_has_no_app_button_without_app_id() -> None:
    api, assistant = FakeApi(), FakeAssistant()

    await handle_message(make_message("/start"), api, assistant, make_settings(), None)

    assert '"open_link"' not in api.log[0]["keyboard"]


async def test_link_command_without_auth_is_refused() -> None:
    api, assistant = FakeApi(), FakeAssistant()

    await handle_message(make_message("/link"), api, assistant, make_settings(), None)

    assert api.log[0]["message"] == "Привязка аккаунта недоступна."


async def test_assistant_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    api, assistant = FakeApi(), FakeAssistant()

    async def boom(*args: Any, **kwargs: Any):
        raise RuntimeError("down")

    monkeypatch.setattr(assistant, "handle_text", boom)

    await handle_message(make_message("привет"), api, assistant, make_settings(), None)

    assert api.log[0]["message"] == ERROR_REPLY


async def test_callback_completes_the_event() -> None:
    api, assistant = FakeApi(), FakeAssistant()

    await handle_callback_payload({"done": 5}, api, assistant, user_id=777, peer_id=777, event_id="evt-1")

    assert assistant.status_calls == [(Platform.VK, "777", 5, EventStatus.DONE)]
    assert "Позвонить в банк" in api.log[0]["message"]
    assert api.messages.answers[0]["event_id"] == "evt-1"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"done": 5}, 5),
        ({"done": "5"}, 5),
        ('{"done": 7}', 7),
        ("done:5", None),
        ({"other": 1}, None),
        (None, None),
    ],
)
def test_event_id_payload_parsing(payload: Any, expected: int | None) -> None:
    assert _event_id_from_payload(payload) == expected


async def test_start_command_with_link_code_redeems_and_confirms() -> None:
    api, assistant = FakeApi(), FakeAssistant()

    class FakeAuth:
        def __init__(self) -> None:
            self.redeemed: list[tuple[Any, str]] = []

        async def redeem(self, identity: Any, code: str) -> None:
            self.redeemed.append((identity, code))

    fake_auth = FakeAuth()
    await handle_message(
        make_message("/start LINK_VK_XYZ"),
        api,
        assistant,
        make_settings(),
        fake_auth,  # type: ignore[arg-type]
    )

    assert len(fake_auth.redeemed) == 1
    assert fake_auth.redeemed[0][1] == "LINK_VK_XYZ"
    assert "привязан" in api.log[0]["message"]

