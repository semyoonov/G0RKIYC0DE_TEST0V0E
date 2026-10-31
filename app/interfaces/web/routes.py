from __future__ import annotations

import base64
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field, field_validator

from app.core.exceptions import AssistantError, NotFoundError
from app.core.logger import get_logger
from app.domain.enums import EventStatus, Period, Platform
from app.domain.models import AssistantResponse, EventRead
from app.interfaces.web.auth_routes import identity_from_request

if TYPE_CHECKING:
    from app.ai.assistant import AssistantService
    from app.core.config import Settings
    from app.services.auth.service import AuthService

log = get_logger(__name__)

QUICK_ACTIONS: tuple[str, ...] = (
    "Что у меня сегодня?",
    "Что на завтра?",
    "Что на этой неделе?",
)
MAX_TEXT_LENGTH = 4000
MAX_AUDIO_BYTES = 20 * 1024 * 1024


class ChatPayload(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    speak: bool = False
    closing: bool = False
    voice: str | None = Field(default=None, max_length=32)

    @field_validator("text")
    @classmethod
    def _require_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("text must not be blank")
        return stripped


class SpeechPayload(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)
    voice: str | None = Field(default=None, max_length=32)


class TelemetryPayload(BaseModel):
    event: str = Field(min_length=1, max_length=64)
    phase: str | None = Field(default=None, max_length=32)
    detail: str | None = Field(default=None, max_length=200)


def _serialize_event(event: EventRead) -> dict[str, Any]:
    return event.model_dump(mode="json")


def _serialize_response(response: AssistantResponse) -> dict[str, Any]:
    audio = base64.b64encode(response.audio).decode("ascii") if response.audio else None
    return {
        "reply": response.text,
        "audio": audio,
        "audio_mime": response.audio_mime_type if audio else None,
        "events": [_serialize_event(event) for event in response.events],
        "needs_clarification": response.needs_clarification,
        "intent": response.intent,
    }


_FALLBACK_HTML = """<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Ассистент задач и встреч</title>
  </head>
  <body style="font-family: system-ui, sans-serif; background: #0f1115; color: #f2f5fa; padding: 2rem">
    <h1>Ассистент задач и встреч</h1>
    <p>Веб-интерфейс ещё не собран. Выполните
      <code>cd frontend &amp;&amp; pnpm install &amp;&amp; pnpm build</code>
      и перезапустите приложение.</p>
  </body>
</html>
"""


async def _conversation_owner(request: Request, auth: AuthService | None) -> tuple[Platform, str]:
    """Идентичность из сессии, а не из id, присланного клиентом."""
    identity = await identity_from_request(request, auth)
    if identity is None:
        raise HTTPException(status_code=401, detail="Войдите в аккаунт, чтобы продолжить.")
    return identity.platform, identity.external_id


def build_router(
    assistant: AssistantService,
    settings: Settings,
    dist_dir: Path | None = None,
    auth: AuthService | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    async def index() -> Response:
        if dist_dir is not None:
            index_file = dist_dir / "index.html"
            if index_file.is_file():
                page = index_file.read_text(encoding="utf-8").replace(
                    "__ASSISTANT_TIMEZONE__", escape(settings.timezone)
                )
                return HTMLResponse(page)
        return HTMLResponse(_FALLBACK_HTML)

    @router.get("/api/meta")
    async def meta() -> dict[str, Any]:
        return {
            "timezone": settings.timezone,
            "quick_actions": list(QUICK_ACTIONS),
            "mini_apps": settings.mini_app_links(),
            "platforms": [platform.value for platform in Platform],
            "voices": settings.tts_voices,
            "voice": settings.tts_voice,
        }

    @router.post("/api/chat")
    async def chat(payload: ChatPayload, request: Request) -> dict[str, Any]:
        platform, external_id = await _conversation_owner(request, auth)
        try:
            response = await assistant.handle_text(
                platform,
                external_id,
                payload.text,
                speak=payload.speak,
                closing=payload.closing,
                voice=payload.voice,
            )
        except AssistantError as exc:
            log.exception("web chat request failed")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_response(response)

    @router.post("/api/chat/warmup")
    async def chat_warmup(request: Request) -> dict[str, Any]:
        await _conversation_owner(request, auth)
        warmed = await assistant.prewarm()
        return {"status": "ok", "warmed": bool(warmed)}

    @router.post("/api/speech")
    async def speech(payload: SpeechPayload, request: Request) -> dict[str, Any]:
        await _conversation_owner(request, auth)
        result = await assistant.speak(payload.text, voice=payload.voice)
        if result is None:
            return {"audio": None, "audio_mime": None, "audio_format": None}
        audio, mime = result
        return {
            "audio": base64.b64encode(audio).decode("ascii"),
            "audio_mime": mime,
            "audio_format": "opus",
        }

    @router.post("/api/telemetry")
    async def telemetry(payload: TelemetryPayload, request: Request) -> dict[str, Any]:
        peer = request.client.host if request.client else "-"
        # Логируется только форма события: текст пользователя сюда не попадает.
        log.info(
            "client telemetry: event=%s phase=%s detail=%s peer=%s",
            payload.event,
            payload.phase or "-",
            payload.detail or "-",
            peer,
        )
        return {"ok": True}

    @router.post("/api/voice")
    async def voice(
        request: Request,
        audio: UploadFile = File(...),
    ) -> dict[str, Any]:
        if audio.size is not None and audio.size > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Аудиофайл больше 20 МБ")
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if not data:
            raise HTTPException(status_code=400, detail="Аудиофайл пустой")
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Аудиофайл больше 20 МБ")
        platform, external_id = await _conversation_owner(request, auth)
        try:
            response = await assistant.handle_voice(
                platform,
                external_id,
                data,
                source_format=None,
                speak=True,
            )
        except AssistantError as exc:
            log.exception("web voice request failed")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_response(response)

    @router.get("/api/events")
    async def list_events(
        request: Request,
        period: Period = Period.TODAY,
    ) -> dict[str, Any]:
        platform, external_id = await _conversation_owner(request, auth)
        try:
            events = await assistant.list_events(platform, external_id, Period(period))
        except AssistantError as exc:
            log.exception("web events request failed")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"events": [_serialize_event(event) for event in events]}

    @router.post("/api/events/{event_id}/complete")
    async def complete_event(
        event_id: int,
        request: Request,
    ) -> dict[str, Any]:
        platform, external_id = await _conversation_owner(request, auth)
        try:
            event = await assistant.set_event_status(platform, external_id, event_id, EventStatus.DONE)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AssistantError as exc:
            log.exception("web event completion failed")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_event(event)

    @router.get("/api/calendar/export.ics")
    async def export_calendar(request: Request) -> Response:
        platform, external_id = await _conversation_owner(request, auth)
        try:
            ics_bytes = await assistant.export_calendar_ics(platform, external_id)
        except AssistantError as exc:
            log.exception("calendar export failed")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            content=ics_bytes,
            media_type="text/calendar; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="gorkycode_calendar.ics"',
                "Cache-Control": "no-cache",
            },
        )

    return router
