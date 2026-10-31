from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.exceptions import TranscriptionError
from app.core.logger import get_logger
from app.services.auth.tokens import SessionTokenError

if TYPE_CHECKING:
    from app.services.auth.service import AuthService

log = get_logger(__name__)

MAX_FRAME_BYTES = 256 * 1024
CLOSE_DISABLED = 1013
CLOSE_POLICY = 1008


class StreamingSession(Protocol):
    async def feed(self, frame: bytes) -> None: ...

    async def next_partial(self) -> str | None: ...

    async def finish(self) -> str: ...

    async def close(self) -> None: ...


StreamingFactory = Callable[[], Awaitable[StreamingSession]]


def build_voice_stream_router(
    streaming_factory: StreamingFactory | None,
    auth: AuthService | None = None,
    max_streams: int = 4,
) -> APIRouter:
    router = APIRouter()
    limit = max(1, max_streams)
    active_streams = 0

    @router.websocket("/ws/voice")
    async def voice_stream(websocket: WebSocket) -> None:
        nonlocal active_streams
        await websocket.accept()
        if streaming_factory is None:
            await websocket.close(code=CLOSE_DISABLED)
            return
        if auth is None:
            await websocket.close(code=CLOSE_POLICY)
            return

        # The browser sends its signed session token as the first WebSocket message.
        # Do not start recording or allocate a recognizer before validating it.
        try:
            raw_auth = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
        except (TimeoutError, WebSocketDisconnect):
            await websocket.close(code=CLOSE_POLICY)
            return
        auth_message = _parse_control(raw_auth)
        token = auth_message.get("token") if auth_message and auth_message.get("type") == "auth" else None
        try:
            account = await auth.account(token if isinstance(token, str) else None)
        except (SessionTokenError, ValueError):
            await websocket.close(code=CLOSE_POLICY)
            return
        external_id = account.identity.external_id

        if active_streams >= limit:
            await websocket.close(code=CLOSE_DISABLED)
            return
        active_streams += 1

        session: StreamingSession | None = None
        try:
            session = await streaming_factory()
            await websocket.send_json({"type": "ready"})
            sender = asyncio.create_task(_relay_partials(websocket, session), name="ws-partials")
            try:
                stop_requested = await _receive_audio(websocket, session)
            finally:
                sender.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sender
            if not stop_requested:
                return
            text = await session.finish()
            if text:
                await websocket.send_json({"type": "final", "text": text})
            else:
                await websocket.send_json({"type": "error", "message": "речь не распознана"})
        except WebSocketDisconnect:
            log.info("voice stream disconnected: user=%s", external_id)
        except TranscriptionError as error:
            await _send_error(websocket, str(error))
        except Exception:  # noqa: BLE001 - the socket must be closed with a message, not a traceback
            log.exception("voice stream failed: user=%s", external_id)
            await _send_error(websocket, "не удалось обработать аудио")
        finally:
            if session is not None:
                await session.close()
            active_streams -= 1
            with contextlib.suppress(Exception):
                await websocket.close()

    return router


async def _receive_audio(websocket: WebSocket, session: StreamingSession) -> bool:
    """Reads frames until the client asks to stop; returns False when it cancelled."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return False
        frame = message.get("bytes")
        if frame:
            if len(frame) > MAX_FRAME_BYTES:
                raise TranscriptionError("слишком большой аудиокадр")
            await session.feed(frame)
            continue
        payload = _parse_control(message.get("text"))
        if payload is None:
            continue
        command = payload.get("type")
        if command == "stop":
            return True
        if command == "cancel":
            return False


def _parse_control(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def _relay_partials(websocket: WebSocket, session: StreamingSession) -> None:
    while True:
        partial = await session.next_partial()
        if partial is None:
            return
        await websocket.send_json({"type": "partial", "text": partial})


async def _send_error(websocket: WebSocket, message: str) -> None:
    with contextlib.suppress(Exception):
        await websocket.send_json({"type": "error", "message": message})
