import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.domain.enums import Period
from app.domain.models import AssistantResponse
from app.interfaces.web import ws as ws_module
from app.interfaces.web.app import create_app


class FakeAssistant:
    async def handle_text(self, platform, external_user_id, text, *, speak=False, audio_format=None):
        return AssistantResponse(text="ответ")

    async def handle_voice(self, platform, external_user_id, audio, *, source_format=None, speak=True, audio_format=None):
        return AssistantResponse(text="ответ")

    async def list_events(self, platform, external_user_id, period=Period.WEEK):
        return []

    async def set_event_status(self, platform, external_user_id, event_id, status):
        return None


class FakeStreamingSession:
    def __init__(self, final_text: str = "поставь задачу") -> None:
        self.frames: list[bytes] = []
        self.closed = False
        self.finished = False
        self.final_text = final_text
        self._partials: asyncio.Queue[str | None] = asyncio.Queue()

    async def feed(self, frame: bytes) -> None:
        self.frames.append(frame)
        await self._partials.put(f"часть {len(self.frames)}")

    async def next_partial(self) -> str | None:
        return await self._partials.get()

    async def finish(self) -> str:
        self.finished = True
        return self.final_text

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def streaming_app(settings):
    sessions: list[FakeStreamingSession] = []

    async def factory() -> FakeStreamingSession:
        session = FakeStreamingSession()
        sessions.append(session)
        return session

    app = create_app(FakeAssistant(), settings, streaming_factory=factory)
    return app, sessions


def receive_until(websocket, message_type: str) -> dict:
    for _ in range(10):
        message = websocket.receive_json()
        if message.get("type") == message_type:
            return message
    raise AssertionError(f"no {message_type} message received")


def test_stream_relays_partials_and_final(streaming_app):
    app, sessions = streaming_app
    with TestClient(app) as client:
        with client.websocket_connect("/ws/voice?client_id=web-demo") as websocket:
            assert websocket.receive_json() == {"type": "ready"}
            websocket.send_bytes(b"\x01\x00" * 320)
            partial = receive_until(websocket, "partial")
            assert partial == {"type": "partial", "text": "часть 1"}

            websocket.send_bytes(b"\x02\x00" * 320)
            websocket.send_json({"type": "stop"})
            final = receive_until(websocket, "final")
            assert final == {"type": "final", "text": "поставь задачу"}

    session = sessions[0]
    assert session.finished is True
    assert session.closed is True
    assert len(session.frames) == 2


def test_stream_reports_empty_recognition(settings):
    async def factory() -> FakeStreamingSession:
        return FakeStreamingSession(final_text="")

    app = create_app(FakeAssistant(), settings, streaming_factory=factory)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/voice") as websocket:
            assert websocket.receive_json() == {"type": "ready"}
            websocket.send_json({"type": "stop"})
            error = receive_until(websocket, "error")
            assert error == {"type": "error", "message": "речь не распознана"}


def test_stream_is_disabled_without_factory(settings):
    app = create_app(FakeAssistant(), settings)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/ws/voice") as websocket:
                websocket.receive_json()
    assert error.value.code == ws_module.CLOSE_DISABLED


def test_stream_rejects_long_client_id(streaming_app):
    app, _ = streaming_app
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect(f"/ws/voice?client_id={'x' * 129}") as websocket:
                websocket.receive_json()
    assert error.value.code == ws_module.CLOSE_POLICY


def test_stream_rejects_oversized_frame(streaming_app):
    app, _ = streaming_app
    with TestClient(app) as client:
        with client.websocket_connect("/ws/voice") as websocket:
            assert websocket.receive_json() == {"type": "ready"}
            websocket.send_bytes(b"\x00" * (ws_module.MAX_FRAME_BYTES + 1))
            error = receive_until(websocket, "error")
            assert error["type"] == "error"


def test_stream_cancel_skips_final(streaming_app):
    app, sessions = streaming_app
    with TestClient(app) as client:
        with client.websocket_connect("/ws/voice") as websocket:
            assert websocket.receive_json() == {"type": "ready"}
            websocket.send_bytes(b"\x00\x00" * 160)
            websocket.send_json({"type": "cancel"})
            with pytest.raises(WebSocketDisconnect):
                for _ in range(5):
                    websocket.receive_json()
    assert sessions[0].finished is False
    assert sessions[0].closed is True


def test_control_messages_ignore_malformed_json(settings):
    app = create_app(FakeAssistant(), settings, streaming_factory=lambda: _session_factory())
    with TestClient(app) as client:
        with client.websocket_connect("/ws/voice") as websocket:
            assert websocket.receive_json() == {"type": "ready"}
            websocket.send_text("not json")
            websocket.send_json({"type": "stop"})
            final = receive_until(websocket, "final")
            assert final["type"] == "final"


async def _session_factory() -> FakeStreamingSession:
    session = FakeStreamingSession(final_text="готово")
    return session


def test_partial_batch_is_json_safe(streaming_app):
    app, _ = streaming_app
    with TestClient(app) as client:
        with client.websocket_connect("/ws/voice") as websocket:
            websocket.receive_json()
            websocket.send_bytes(b"\x00\x00" * 160)
            partial = receive_until(websocket, "partial")
            json.dumps(partial)
