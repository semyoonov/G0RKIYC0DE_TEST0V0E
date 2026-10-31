from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.core.exceptions import AssistantError, ExternalServiceError
from app.domain.enums import EventStatus, EventType, Platform
from app.domain.models import AssistantResponse, EventRead
from app.interfaces.cards import cards_text
from app.interfaces.max.bot import MaxClient
from app.interfaces.max.handlers import handle_update

BASE_URL = "https://platform-api2.max.ru"
TOKEN = "max-test-token"
MOSCOW = ZoneInfo("Europe/Moscow")
UTC = timezone.utc
CREATED_AT = datetime(2025, 3, 1, 9, 0, tzinfo=UTC)
STARTED_AT = datetime(2021, 5, 14, 7, 30, tzinfo=UTC)
Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler) -> MaxClient:
    return MaxClient(BASE_URL, TOKEN, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def make_event(
    event_id: int = 7,
    *,
    event_type: EventType = EventType.REMINDER,
    title: str = "Позвонить в банк",
    starts_at: datetime | None = STARTED_AT,
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


class StubAssistant:
    def __init__(
        self,
        response: AssistantResponse | None = None,
        *,
        status_event: EventRead | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or AssistantResponse(text="Записал")
        self.status_event = status_event or make_event(status=EventStatus.DONE)
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
        return self.status_event


async def test_get_updates_sends_raw_token_and_marker() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["marker"] = request.url.params.get("marker")
        seen["timeout"] = request.url.params.get("timeout")
        return httpx.Response(200, json={"updates": [], "marker": 11})

    client = make_client(handler)
    try:
        payload = await client.get_updates(marker=7, timeout=20)
    finally:
        await client.close()

    assert payload == {"updates": [], "marker": 11}
    assert seen == {
        "authorization": TOKEN,
        "method": "GET",
        "path": "/updates",
        "marker": "7",
        "timeout": "20",
    }


async def test_send_text_posts_to_messages_with_user_id() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["user_id"] = request.url.params.get("user_id")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"body": {"mid": "m-1"}}})

    client = make_client(handler)
    try:
        payload = await client.send_text(42, "Привет")
    finally:
        await client.close()

    assert payload == {"message": {"body": {"mid": "m-1"}}}
    assert seen["authorization"] == TOKEN
    assert seen["method"] == "POST"
    assert seen["path"] == "/messages"
    assert seen["user_id"] == "42"
    assert seen["body"] == {"text": "Привет"}


async def test_send_text_attaches_inline_keyboard() -> None:
    seen: dict[str, Any] = {}
    buttons = [[{"type": "callback", "text": "✅ Выполнено", "payload": "event:done:7"}]]

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["user_id"] = request.url.params.get("user_id")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    try:
        await client.send_text(42, "Карточка", buttons=buttons)
    finally:
        await client.close()

    assert seen["authorization"] == TOKEN
    assert seen["method"] == "POST"
    assert seen["path"] == "/messages"
    assert seen["user_id"] == "42"
    assert seen["body"] == {
        "text": "Карточка",
        "attachments": [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        [{"type": "callback", "text": "✅ Выполнено", "payload": "event:done:7"}]
                    ]
                },
            }
        ],
    }


async def test_send_text_omits_attachments_when_buttons_empty() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    try:
        await client.send_text(1, "Без кнопок", buttons=[])
    finally:
        await client.close()

    assert seen["body"] == {"text": "Без кнопок"}


async def test_answer_callback_posts_callback_id() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["callback_id"] = request.url.params.get("callback_id")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True})

    client = make_client(handler)
    try:
        payload = await client.answer_callback("cb-1")
    finally:
        await client.close()

    assert payload == {"success": True}
    assert seen == {
        "authorization": TOKEN,
        "method": "POST",
        "path": "/answers",
        "callback_id": "cb-1",
        "body": {},
    }


async def test_send_audio_uploads_then_sends_attachment() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/uploads":
            assert request.method == "POST"
            assert request.url.params.get("type") == "audio"
            assert request.headers.get("authorization") == TOKEN
            return httpx.Response(200, json={"url": "https://upload.example/file/1"})
        if request.url.host == "upload.example":
            assert request.method == "PUT"
            assert request.headers.get("authorization") is None
            assert request.headers["content-type"].startswith("multipart/form-data")
            assert b'name="data"' in request.content
            assert b"OPUS-BYTES" in request.content
            return httpx.Response(200, json={"token": "file-token"})
        if request.url.path == "/messages":
            assert request.headers.get("authorization") == TOKEN
            assert request.url.params.get("user_id") == "7"
            assert json.loads(request.content) == {
                "attachments": [{"type": "audio", "payload": {"token": "file-token"}}]
            }
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = make_client(handler)
    try:
        payload = await client.send_audio(7, b"OPUS-BYTES", filename="answer.opus")
    finally:
        await client.close()

    assert payload == {"ok": True}
    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/uploads"),
        ("PUT", "/file/1"),
        ("POST", "/messages"),
    ]


async def test_non_2xx_raises_external_service_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized token")

    client = make_client(handler)
    try:
        with pytest.raises(ExternalServiceError) as excinfo:
            await client.send_text(1, "Привет")
    finally:
        await client.close()

    assert excinfo.value.status_code == 401
    assert excinfo.value.service == "max"
    assert "401" in str(excinfo.value)


async def test_upload_failure_raises_external_service_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/uploads":
            return httpx.Response(200, json={"url": "https://upload.example/file/1"})
        return httpx.Response(413, text="file too large")

    client = make_client(handler)
    try:
        with pytest.raises(ExternalServiceError) as excinfo:
            await client.send_audio(3, b"x" * 8)
    finally:
        await client.close()

    assert excinfo.value.status_code == 413


async def test_handle_update_dispatches_text_message() -> None:
    assistant = StubAssistant()
    replies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/messages"
        assert request.url.params.get("user_id") == "777"
        replies.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    update = {
        "update_type": "message_created",
        "timestamp": 1700000000,
        "message": {
            "sender": {"user_id": 777, "name": "Иван"},
            "body": {"mid": "m-1", "seq": 1, "text": "Что у меня сегодня?"},
        },
    }
    try:
        await handle_update(client, update, assistant, MOSCOW)
    finally:
        await client.close()

    assert assistant.text_calls == [(Platform.MAX, "777", "Что у меня сегодня?", False)]
    assert replies == [{"text": "Записал"}]


async def test_handle_update_sends_card_with_done_buttons() -> None:
    event = make_event(7, starts_at=STARTED_AT)
    assistant = StubAssistant(
        AssistantResponse(text="Напоминание создано.", events=[event], intent="create_task")
    )
    replies: list[dict[str, Any]] = []
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.method == "POST"
        assert request.url.params.get("user_id") == "777"
        assert request.headers.get("authorization") == TOKEN
        replies.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    update = {
        "update_type": "message_created",
        "message": {"sender": {"user_id": 777}, "body": {"text": "Напомни позвонить в банк"}},
    }
    try:
        await handle_update(client, update, assistant, MOSCOW)
    finally:
        await client.close()

    assert paths == ["/messages", "/messages"]
    assert len(replies) == 2
    assert replies[0] == {"text": "Напоминание создано."}
    assert replies[1] == {
        "text": cards_text([event], MOSCOW, "Создано"),
        "attachments": [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        [{"type": "callback", "text": "✅ Выполнено", "payload": "event:done:7"}]
                    ]
                },
            }
        ],
    }
    assert "Создано" in replies[1]["text"].splitlines()[0]


async def test_handle_update_sends_card_without_buttons_for_done_events() -> None:
    event = make_event(7, status=EventStatus.DONE)
    assistant = StubAssistant(AssistantResponse(text="Готовые задачи.", events=[event]))
    replies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        replies.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    update = {
        "update_type": "message_created",
        "message": {"sender": {"user_id": 777}, "body": {"text": "Что выполнено?"}},
    }
    try:
        await handle_update(client, update, assistant, MOSCOW)
    finally:
        await client.close()

    assert replies[1] == {"text": cards_text([event], MOSCOW)}


async def test_handle_update_dispatches_voice_attachment() -> None:
    assistant = StubAssistant(AssistantResponse(text="Расшифровал"))
    downloads: list[str] = []
    replies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.example":
            downloads.append(request.url.path)
            return httpx.Response(200, content=b"OGG-PAYLOAD", headers={"content-type": "audio/ogg"})
        assert request.url.path == "/messages"
        replies.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    update = {
        "update_type": "message_created",
        "timestamp": 1700000001,
        "message": {
            "sender": {"user_id": 555},
            "body": {
                "mid": "m-2",
                "seq": 2,
                "attachments": [
                    {
                        "type": "voice",
                        "payload": {"url": "https://cdn.example/voice/1.ogg", "token": "audio-token"},
                    }
                ],
            },
        },
    }
    try:
        await handle_update(client, update, assistant, MOSCOW)
    finally:
        await client.close()

    assert downloads == ["/voice/1.ogg"]
    assert assistant.voice_calls == [(Platform.MAX, "555", b"OGG-PAYLOAD", None, False)]
    assert replies == [{"text": "Расшифровал"}]


async def test_handle_update_greets_on_start_command() -> None:
    assistant = StubAssistant()
    replies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        replies.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    update = {
        "update_type": "message_created",
        "message": {"sender": {"user_id": 9}, "body": {"mid": "m-3", "text": "/start"}},
    }
    try:
        await handle_update(client, update, assistant, MOSCOW)
    finally:
        await client.close()

    assert assistant.text_calls == []
    assert len(replies) == 1
    assert "Привет" in replies[0]["text"]


async def test_handle_update_greets_on_bot_started() -> None:
    assistant = StubAssistant()
    replies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        replies.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    update = {
        "update_type": "bot_started",
        "chat_id": 99,
        "user": {"user_id": 99, "name": "Тестер"},
    }
    try:
        await handle_update(client, update, assistant, MOSCOW)
    finally:
        await client.close()

    assert len(replies) == 1
    assert "Привет" in replies[0]["text"]


async def test_handle_update_ignores_non_message_updates() -> None:
    assistant = StubAssistant()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP calls expected")

    client = make_client(handler)
    try:
        await handle_update(client, {"update_type": "bot_started", "timestamp": 1}, assistant, MOSCOW)
    finally:
        await client.close()

    assert assistant.text_calls == []
    assert assistant.voice_calls == []
    assert assistant.status_calls == []


async def test_handle_update_routes_message_callback() -> None:
    assistant = StubAssistant(status_event=make_event(7, status=EventStatus.DONE))
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "method": request.method,
                "path": request.url.path,
                "callback_id": request.url.params.get("callback_id"),
                "authorization": request.headers.get("authorization"),
                "body": json.loads(request.content),
            }
        )
        return httpx.Response(200, json={"success": True})

    client = make_client(handler)
    update = {
        "update_type": "message_callback",
        "timestamp": 1700000002,
        "callback": {
            "timestamp": 1700000002,
            "callback_id": "cb-1",
            "payload": "event:done:7",
            "user": {"user_id": 4242, "name": "Иван"},
        },
        "message": {"sender": {"user_id": 1}, "body": {"mid": "m-4", "text": "Карточка"}},
    }
    try:
        await handle_update(client, update, assistant, MOSCOW)
    finally:
        await client.close()

    assert assistant.status_calls == [(Platform.MAX, "4242", 7, EventStatus.DONE)]
    assert calls == [
        {
            "method": "POST",
            "path": "/answers",
            "callback_id": "cb-1",
            "authorization": TOKEN,
            "body": {},
        }
    ]


async def test_message_callback_falls_back_to_message_sender() -> None:
    assistant = StubAssistant()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/answers"
        return httpx.Response(200, json={"success": True})

    client = make_client(handler)
    update = {
        "update_type": "message_callback",
        "callback": {"callback_id": "cb-2", "payload": "event:done:7"},
        "message": {"sender": {"user_id": 99}, "body": {"text": "Карточка"}},
    }
    try:
        await handle_update(client, update, assistant, MOSCOW)
    finally:
        await client.close()

    assert assistant.status_calls == [(Platform.MAX, "99", 7, EventStatus.DONE)]


async def test_message_callback_ignores_unknown_payload() -> None:
    assistant = StubAssistant()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP calls expected")

    client = make_client(handler)
    update = {
        "update_type": "message_callback",
        "callback": {"callback_id": "cb-3", "payload": "event:delete:7", "user": {"user_id": 5}},
    }
    try:
        await handle_update(client, update, assistant, MOSCOW)
    finally:
        await client.close()

    assert assistant.status_calls == []


async def test_message_callback_without_callback_id_skips_answers() -> None:
    assistant = StubAssistant()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP calls expected")

    client = make_client(handler)
    update = {
        "update_type": "message_callback",
        "callback": {"payload": "event:done:7", "user": {"user_id": 5}},
    }
    try:
        await handle_update(client, update, assistant, MOSCOW)
    finally:
        await client.close()

    assert assistant.status_calls == [(Platform.MAX, "5", 7, EventStatus.DONE)]


async def test_message_callback_acknowledgement_failure_is_logged_and_ignored() -> None:
    assistant = StubAssistant()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="answers are unavailable")

    client = make_client(handler)
    update = {
        "update_type": "message_callback",
        "callback": {"callback_id": "cb-4", "payload": "event:done:7", "user": {"user_id": 5}},
    }
    try:
        await handle_update(client, update, assistant, MOSCOW)
    finally:
        await client.close()

    assert assistant.status_calls == [(Platform.MAX, "5", 7, EventStatus.DONE)]


async def test_message_callback_reports_assistant_error() -> None:
    assistant = StubAssistant(error=AssistantError("boom"))
    replies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        replies.append(
            {"path": request.url.path, "body": json.loads(request.content), "callback_id": request.url.params.get("callback_id")}
        )
        return httpx.Response(200, json={"success": True})

    client = make_client(handler)
    update = {
        "update_type": "message_callback",
        "callback": {"callback_id": "cb-5", "payload": "event:done:7", "user": {"user_id": 5}},
    }
    try:
        await handle_update(client, update, assistant, MOSCOW)
    finally:
        await client.close()

    assert assistant.status_calls == [(Platform.MAX, "5", 7, EventStatus.DONE)]
    assert replies[0] == {
        "path": "/messages",
        "body": {"text": "Не получилось обработать запрос, попробуйте ещё раз."},
        "callback_id": None,
    }
    assert replies[1]["callback_id"] == "cb-5"
