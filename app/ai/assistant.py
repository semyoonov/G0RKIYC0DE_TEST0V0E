import json
import re
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.llm.gigachat_client import ChatCompletion
from app.ai.llm.prompts import build_system_prompt
from app.ai.llm.replies import recover_calls, sanitize_reply
from app.ai.llm.tool_executor import ERROR_PREFIX, ToolExecutor, to_read
from app.ai.llm.tools import TOOLS_SCHEMA
from app.ai.nlp.scope import OFF_TOPIC_REPLY, is_off_topic
from app.core.config import Settings
from app.core.exceptions import AssistantError, LLMError, NotFoundError
from app.core.logger import get_logger
from app.core.timeutils import period_bounds
from app.domain.enums import EventStatus, Period, Platform
from app.domain.models import AssistantResponse, EventRead, EventUpdate
from app.repositories.event_repository import EventRepository
from app.repositories.user_repository import UserRepository
from app.services.cache.redis_service import CacheService
from app.services.demo_seed import seed_demo_events

log = get_logger(__name__)

CLARIFICATION_TEXT = (
    "Не понял запрос. Скажите, например: «Напомни завтра в 10 позвонить Ивану» "
    "или «Что у меня сегодня?»."
)
ERROR_TEXT = "Не получилось обработать запрос. Попробуйте ещё раз."
TRANSCRIPTION_ERROR_TEXT = "Не удалось распознать речь. Запишите сообщение ещё раз или напишите текстом."
LLM_DISABLED_TEXT = (
    "GigaChat не настроен: задайте GIGACHAT_CREDENTIALS, чтобы ассистент отвечал на запросы."
)

_ID_MARKER_RE = re.compile(r"\s*\[id \d+\]")
_BLOCKED_FINISH_REASONS = frozenset({"blacklist", "content_filter", "sensitive"})


def _humanize(answer: str) -> str:
    return _ID_MARKER_RE.sub("", sanitize_reply(answer)).strip()


def _normalize_audio_format(value: str | None) -> str | None:
    if value is None:
        return None
    lowered = value.lower()
    return "wav" if lowered == "wav16" else lowered


class ChatModel(Protocol):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatCompletion: ...


class SpeechRecognizer(Protocol):
    async def transcribe(self, wav_bytes: bytes) -> str: ...


class SpeechSynthesizer(Protocol):
    async def synthesize(self, text: str, *, audio_format: str | None = None) -> bytes: ...


class AudioTranscoder(Protocol):
    async def to_wav(self, data: bytes, source_hint: str | None = None) -> bytes: ...


CLOSING_RULE = (
    "Пользователь завершает голосовой диалог. Не создавай и не меняй события. "
    "Ответь одной короткой фразой: подтверди, что всё записано, и скажи, что ты рядом, "
    "когда понадобишься."
)


class AssistantService:
    """One entry point for every interface: audio/text in, text and optional audio out."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        llm: ChatModel | None = None,
        stt: SpeechRecognizer | None = None,
        tts: SpeechSynthesizer | None = None,
        converter: AudioTranscoder | None = None,
        cache: CacheService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._llm = llm
        self._stt = stt
        self._tts = tts
        self._converter = converter
        self._cache = cache

    def _users(self, session: AsyncSession) -> UserRepository:
        return UserRepository(session, on_created=self._seed_demo_events if self._settings.demo_seed_enabled else None)

    async def _seed_demo_events(self, session: AsyncSession, user) -> None:
        await seed_demo_events(session, user, self._settings.timezone)

    @property
    def llm_enabled(self) -> bool:
        return self._llm is not None and self._settings.gigachat_enabled

    async def handle_text(
        self,
        platform: Platform,
        external_user_id: str,
        text: str,
        *,
        speak: bool = False,
        audio_format: str | None = None,
        closing: bool = False,
        voice: str | None = None,
    ) -> AssistantResponse:
        normalized = " ".join((text or "").split())
        if not normalized:
            return AssistantResponse(text=CLARIFICATION_TEXT, needs_clarification=True)
        if is_off_topic(normalized):
            return AssistantResponse(text=OFF_TOPIC_REPLY)
        if self._llm is None:
            return AssistantResponse(text=LLM_DISABLED_TEXT)
        try:
            response = await self._process(platform, external_user_id, normalized, closing=closing)
        except AssistantError as error:
            log.warning("assistant failed: %s", error)
            return AssistantResponse(text=ERROR_TEXT)
        except Exception:
            log.exception("assistant crashed")
            return AssistantResponse(text=ERROR_TEXT)
        if speak:
            await self._attach_audio(
                response, self._preferred_audio_format(platform, audio_format), voice
            )
        return response

    async def speak(self, text: str, *, voice: str | None = None) -> tuple[bytes, str] | None:
        """Synthesises text on demand so the client can render the reply before its audio."""
        if self._tts is None or not self._settings.tts_enabled:
            return None
        normalized = " ".join((text or "").split())
        if not normalized:
            return None
        requested = _normalize_audio_format(self._settings.sber_tts_format)
        try:
            audio = await self._tts.synthesize(normalized, audio_format=requested, voice=voice)
        except AssistantError as error:
            log.warning("speech synthesis failed: %s", error)
            return None
        if not audio:
            return None
        mime = AssistantResponse(text="", audio=audio, audio_format=requested).audio_mime_type
        return audio, mime or "application/octet-stream"

    async def prewarm(self) -> bool:
        """Sends the system prompt ahead of the first utterance so the first answer starts faster."""
        if self._llm is None or not self._settings.gigachat_enabled:
            return False
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(self._settings.tz)},
            {"role": "user", "content": "Проверка связи. Ответь одним словом."},
        ]
        try:
            await self._llm.chat(messages, max_tokens=1)
        except Exception as error:  # noqa: BLE001 - a warmup must never surface as an error
            log.info("llm prewarm skipped: %s", error)
            return False
        return True

    async def handle_voice(
        self,
        platform: Platform,
        external_user_id: str,
        audio: bytes,
        *,
        source_format: str | None = None,
        speak: bool = True,
        audio_format: str | None = None,
    ) -> AssistantResponse:
        if not audio:
            return AssistantResponse(text=TRANSCRIPTION_ERROR_TEXT)
        if self._llm is None:
            return AssistantResponse(text=LLM_DISABLED_TEXT)
        if self._stt is None:
            return AssistantResponse(text="Распознавание речи недоступно. Напишите запрос текстом.")
        try:
            wav_bytes = audio
            if self._converter is not None:
                wav_bytes = await self._converter.to_wav(audio, source_format)
            transcript = (await self._stt.transcribe(wav_bytes)).strip()
        except AssistantError as error:
            log.warning("voice pipeline failed: %s", error)
            return AssistantResponse(text=TRANSCRIPTION_ERROR_TEXT)
        if not transcript:
            return AssistantResponse(text=TRANSCRIPTION_ERROR_TEXT)
        return await self.handle_text(
            platform,
            external_user_id,
            transcript,
            speak=speak,
            audio_format=audio_format,
        )

    async def list_events(
        self,
        platform: Platform,
        external_user_id: str,
        period: Period = Period.WEEK,
    ) -> list[EventRead]:
        start, end = period_bounds(period, self._settings.tz)
        async with self._session_factory() as session:
            user = await self._users(session).get_or_create(platform, external_user_id)
            events = await EventRepository(session).list_for_period(
                user.id,
                start,
                end,
                include_undated=period is Period.ALL,
            )
            return [to_read(event) for event in events]

    async def export_calendar_ics(
        self,
        platform: Platform,
        external_user_id: str,
        timezone_name: str | None = None,
    ) -> bytes:
        from app.services.calendar_export import export_events_to_ics
        tz_name = timezone_name or self._settings.timezone
        async with self._session_factory() as session:
            user = await self._users(session).get_or_create(platform, external_user_id)
            events = await EventRepository(session).list_all_for_user(user.id)
            return export_events_to_ics(events, timezone_name=tz_name)

    async def set_event_status(
        self,
        platform: Platform,
        external_user_id: str,
        event_id: int,
        status: EventStatus,
    ) -> EventRead:
        async with self._session_factory() as session:
            user = await self._users(session).get_or_create(platform, external_user_id)
            repository = EventRepository(session)
            event = await repository.get_for_user(user.id, event_id)
            if event is None:
                raise NotFoundError(f"event {event_id} not found")
            if status is EventStatus.DONE:
                event = await repository.mark_done(event, done=True)
            elif status is EventStatus.PENDING:
                event = await repository.mark_done(event, done=False)
            else:
                event = await repository.update(event, EventUpdate(status=status))
            result = to_read(event)
        if self._cache is not None:
            await self._cache.delete_prefix(f"user:{user.id}:")
        return result

    async def close(self) -> None:
        for component in (self._llm, self._tts):
            closer = getattr(component, "close", None)
            if closer is None:
                continue
            result = closer()
            if hasattr(result, "__await__"):
                await result

    async def _process(
        self,
        platform: Platform,
        external_user_id: str,
        text: str,
        *,
        closing: bool = False,
    ) -> AssistantResponse:
        async with self._session_factory() as session:
            user = await self._users(session).get_or_create(platform, external_user_id)
            executor = ToolExecutor(session, user, self._settings, self._cache)
            # End the read transaction so the connection is not held during model and messenger calls.
            await session.commit()
            answer, events, intent = await self._run_llm(user.id, text, executor, closing=closing)
        return AssistantResponse(
            text=_humanize(answer),
            events=events,
            needs_clarification=answer.strip().endswith("?") or answer == CLARIFICATION_TEXT,
            intent=intent,
        )

    async def _run_llm(
        self,
        user_id: int,
        text: str,
        executor: ToolExecutor,
        *,
        closing: bool = False,
    ) -> tuple[str, list[EventRead], str | None]:
        assert self._llm is not None
        # GigaChat accepts exactly one system message and it has to come first, so the
        # closing rule is folded into the prompt instead of being a second system message.
        system_prompt = build_system_prompt(self._settings.tz)
        if closing:
            system_prompt = f"{system_prompt}\n\n{CLOSING_RULE}"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(await self._load_history(user_id))
        messages.append({"role": "user", "content": text})

        intent: str | None = None
        collected: list[EventRead] = []
        answer = ""
        last_tool_content = ""
        for _ in range(max(1, self._settings.tool_max_iterations)):
            try:
                completion = await self._llm.chat(messages, tools=TOOLS_SCHEMA)
            except AssistantError as error:
                if not last_tool_content:
                    raise
                log.warning("llm failed after a tool call, using its result: %s", error)
                answer = self._strip_error(last_tool_content)
                break
            if completion.finish_reason in _BLOCKED_FINISH_REASONS:
                raise LLMError(f"GigaChat stopped the answer: {completion.finish_reason}")

            call = completion.function_call
            recovered = []
            if call is None:
                # GigaChat sometimes serialises the call into the text. Execute it
                # instead of showing the JSON to the user and losing the action.
                recovered, completion_content = recover_calls(completion.content or "")
                if not recovered:
                    answer = completion.content.strip()
                    break

            if call is not None:
                calls: list[tuple[str, dict[str, Any] | str]] = [(call.name, call.arguments)]
                echoed = completion.content or ""
            else:
                calls = [(item.name, item.arguments) for item in recovered]
                echoed = ""

            for name, arguments in calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": echoed,
                        "function_call": {
                            "name": name,
                            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                )
                result = await executor.execute(name, arguments)
                intent = name
                collected.extend(result.events)
                last_tool_content = result.content
                messages.append(
                    {
                        "role": "function",
                        "name": name,
                        # GigaChat rejects a plain sentence here: the function reply must be JSON.
                        "content": json.dumps({"result": result.content}, ensure_ascii=False),
                    }
                )

        if not answer:
            answer = self._strip_error(last_tool_content) if last_tool_content else CLARIFICATION_TEXT
        answer = _humanize(answer)
        if not answer and last_tool_content:
            answer = _humanize(self._strip_error(last_tool_content))
        await self._save_history(user_id, text, answer)
        return answer, collected, intent

    @staticmethod
    def _strip_error(content: str) -> str:
        if content.startswith(ERROR_PREFIX):
            stripped = content[len(ERROR_PREFIX) :].strip()
            return stripped[:1].upper() + stripped[1:]
        return content

    async def _load_history(self, user_id: int) -> list[dict[str, str]]:
        if self._cache is None:
            return []
        limit = max(1, self._settings.conversation_history_turns) * 2
        try:
            entries = await self._cache.get_history(f"history:{user_id}", limit)
        except Exception:
            log.exception("cannot read dialogue history")
            return []
        return [
            {"role": entry["role"], "content": entry["content"]}
            for entry in entries
            if entry.get("role") in ("user", "assistant") and entry.get("content")
        ]

    async def _save_history(self, user_id: int, request_text: str, answer: str) -> None:
        if self._cache is None:
            return
        limit = max(1, self._settings.conversation_history_turns) * 2
        try:
            await self._cache.push_history(f"history:{user_id}", {"role": "user", "content": request_text}, limit)
            await self._cache.push_history(f"history:{user_id}", {"role": "assistant", "content": answer}, limit)
        except Exception:
            log.exception("cannot store dialogue history")

    @staticmethod
    def _preferred_audio_format(platform: Platform, requested: str | None) -> str | None:
        if platform is Platform.TELEGRAM:
            return "opus"
        return requested

    async def _attach_audio(
        self,
        response: AssistantResponse,
        audio_format: str | None,
        voice: str | None = None,
    ) -> None:
        if self._tts is None or not self._settings.tts_enabled or not response.text:
            return
        requested = _normalize_audio_format(audio_format or self._settings.sber_tts_format)
        try:
            audio = await self._tts.synthesize(response.text, audio_format=requested, voice=voice)
        except AssistantError as error:
            log.warning("speech synthesis failed: %s", error)
            return
        if audio:
            response.audio = audio
            response.audio_format = requested
