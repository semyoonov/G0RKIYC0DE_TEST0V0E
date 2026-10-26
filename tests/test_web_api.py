from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.core.exceptions import AssistantError
from app.domain.enums import EventStatus, EventType, Period, Platform
from app.domain.models import AssistantResponse, EventRead
from app.interfaces.web.app import create_app

FIXED_TIME = datetime(2025, 5, 20, 9, 30, tzinfo=timezone.utc)


def make_event(
    event_id: int = 1,
    *,
    status: EventStatus = EventStatus.PENDING,
    title: str = "Встреча с Анной",
) -> EventRead:
    return EventRead(
        id=event_id,
        user_id=1,
        type=EventType.MEETING,
        title=title,
        description=None,
        starts_at=FIXED_TIME,
        remind_at=None,
        status=status,
        source=Platform.WEB,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )


class FakeAssistant:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.prewarm_calls = 0
        self.voices: list[str | None] = []
        self.text_calls: list[tuple[Platform, str, str, bool, bool]] = []
        self.voice_calls: list[tuple[Platform, str, bytes, str | None, bool]] = []
        self.list_calls: list[tuple[Platform, str, Period]] = []
        self.status_calls: list[tuple[Platform, str, int, EventStatus]] = []

    async def prewarm(self) -> bool:
        self.prewarm_calls += 1
        return True

    async def handle_text(
        self,
        platform: Platform,
        external_user_id: str,
        text: str,
        *,
        speak: bool = False,
        closing: bool = False,
        voice: str | None = None,
    ) -> AssistantResponse:
        if self.fail:
            raise AssistantError("сервис недоступен")
        self.text_calls.append((platform, external_user_id, text, speak, closing))
        self.voices.append(voice)
        return AssistantResponse(text=f"Ответ: {text}", events=[make_event(1)])

    async def handle_voice(
        self,
        platform: Platform,
        external_user_id: str,
        audio: bytes,
        *,
        source_format: str | None = None,
        speak: bool = True,
    ) -> AssistantResponse:
        if self.fail:
            raise AssistantError("сервис недоступен")
        self.voice_calls.append((platform, external_user_id, audio, source_format, speak))
        return AssistantResponse(text="Голосовой ответ", audio=b"OPUS-DATA", audio_format="opus")

    async def list_events(self, platform: Platform, external_user_id: str, period: Period) -> list[EventRead]:
        if self.fail:
            raise AssistantError("сервис недоступен")
        self.list_calls.append((platform, external_user_id, period))
        return [make_event(2, title="Позвонить в банк")]

    async def set_event_status(
        self,
        platform: Platform,
        external_user_id: str,
        event_id: int,
        status: EventStatus,
    ) -> EventRead:
        if self.fail:
            raise AssistantError("сервис недоступен")
        self.status_calls.append((platform, external_user_id, event_id, status))
        return make_event(event_id, status=status)


def build_app(assistant: FakeAssistant) -> Any:
    return create_app(assistant, Settings())


async def request(app: Any, method: str, url: str, **kwargs: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


async def test_healthz() -> None:
    response = await request(build_app(FakeAssistant()), "GET", "/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_index_renders_product_page() -> None:
    response = await request(build_app(FakeAssistant()), "GET", "/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Ассистент задач и встреч" in response.text


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html").is_file(),
    reason="frontend dist is not built",
)
async def test_index_injects_assistant_timezone() -> None:
    response = await request(build_app(FakeAssistant()), "GET", "/")

    assert 'name="assistant-timezone"' in response.text
    assert 'content="Europe/Moscow"' in response.text


async def test_meta_exposes_quick_actions_and_timezone() -> None:
    response = await request(build_app(FakeAssistant()), "GET", "/api/meta")

    assert response.status_code == 200
    body = response.json()
    assert "Что у меня сегодня?" in body["quick_actions"]
    assert body["timezone"]


async def test_chat_returns_reply_and_events() -> None:
    assistant = FakeAssistant()
    response = await request(build_app(assistant), "POST", "/api/chat", json={"text": "привет"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Ответ: привет"
    assert body["audio"] is None
    assert body["audio_mime"] is None
    assert body["needs_clarification"] is False
    assert len(body["events"]) == 1
    event = body["events"][0]
    assert event["id"] == 1
    assert event["title"] == "Встреча с Анной"
    assert event["status"] == "pending"
    parsed = datetime.fromisoformat(event["starts_at"])
    assert parsed == FIXED_TIME
    assert assistant.text_calls == [(Platform.WEB, "web-demo", "привет", False, False)]


async def test_chat_uses_explicit_client_id() -> None:
    assistant = FakeAssistant()
    response = await request(
        build_app(assistant),
        "POST",
        "/api/chat",
        json={"text": "план", "client_id": "web-test"},
    )

    assert response.status_code == 200
    assert assistant.text_calls == [(Platform.WEB, "web-test", "план", False, False)]


async def test_chat_forwards_speak_flag() -> None:
    assistant = FakeAssistant()
    response = await request(
        build_app(assistant),
        "POST",
        "/api/chat",
        json={"text": "план", "speak": True},
    )

    assert response.status_code == 200
    assert assistant.text_calls == [(Platform.WEB, "web-demo", "план", True, False)]


async def test_chat_rejects_empty_text() -> None:
    assistant = FakeAssistant()
    app = build_app(assistant)

    empty = await request(app, "POST", "/api/chat", json={"text": ""})
    blank = await request(app, "POST", "/api/chat", json={"text": "   "})

    assert empty.status_code == 422
    assert blank.status_code == 422
    assert assistant.text_calls == []


async def test_chat_maps_assistant_error_to_400() -> None:
    response = await request(build_app(FakeAssistant(fail=True)), "POST", "/api/chat", json={"text": "привет"})

    assert response.status_code == 400
    assert response.json() == {"detail": "сервис недоступен"}


async def test_voice_returns_audio_base64() -> None:
    assistant = FakeAssistant()
    response = await request(
        build_app(assistant),
        "POST",
        "/api/voice",
        data={"client_id": "web-voice"},
        files={"audio": ("voice.webm", b"WEBM-DATA", "audio/webm")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Голосовой ответ"
    assert body["audio"] == base64.b64encode(b"OPUS-DATA").decode("ascii")
    assert body["audio_mime"] == "audio/ogg"
    assert assistant.voice_calls == [(Platform.WEB, "web-voice", b"WEBM-DATA", None, True)]


async def test_voice_rejects_empty_file() -> None:
    response = await request(
        build_app(FakeAssistant()),
        "POST",
        "/api/voice",
        files={"audio": ("voice.webm", b"", "audio/webm")},
    )

    assert response.status_code == 400


async def test_events_by_period() -> None:
    assistant = FakeAssistant()
    response = await request(build_app(assistant), "GET", "/api/events", params={"period": "today"})

    assert response.status_code == 200
    events = response.json()["events"]
    assert [event["id"] for event in events] == [2]
    assert assistant.list_calls == [(Platform.WEB, "web-demo", Period.TODAY)]


async def test_events_reject_unknown_period() -> None:
    response = await request(build_app(FakeAssistant()), "GET", "/api/events", params={"period": "month"})

    assert response.status_code == 422


async def test_complete_event_returns_updated_status() -> None:
    assistant = FakeAssistant()
    response = await request(
        build_app(assistant),
        "POST",
        "/api/events/1/complete",
        params={"client_id": "web-demo"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["status"] == "done"
    assert assistant.status_calls == [(Platform.WEB, "web-demo", 1, EventStatus.DONE)]


async def test_chat_forwards_the_closing_flag() -> None:
    assistant = FakeAssistant()
    response = await request(
        build_app(assistant),
        "POST",
        "/api/chat",
        json={"text": "спасибо", "client_id": "web-demo", "closing": True},
    )

    assert response.status_code == 200
    assert assistant.text_calls == [(Platform.WEB, "web-demo", "спасибо", False, True)]


async def test_chat_warmup_reports_that_the_model_is_ready() -> None:
    assistant = FakeAssistant()
    response = await request(build_app(assistant), "POST", "/api/chat/warmup")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert assistant.prewarm_calls == 1


async def test_meta_exposes_the_voice_catalogue() -> None:
    assistant = FakeAssistant()
    response = await request(build_app(assistant), "GET", "/api/meta")

    assert response.status_code == 200
    body = response.json()
    assert "Mer-Operator" in body["voices"]
    assert body["voice"] == "Mer-Operator"


async def test_chat_forwards_the_selected_voice() -> None:
    assistant = FakeAssistant()
    response = await request(
        build_app(assistant),
        "POST",
        "/api/chat",
        json={"text": "Что на завтра?", "client_id": "web-demo", "speak": True, "voice": "Kaz-Lifelike"},
    )

    assert response.status_code == 200
    assert assistant.voices == ["Kaz-Lifelike"]
