import json
from datetime import datetime, timedelta, timezone

import pytest
from fakeredis.aioredis import FakeRedis

from app.ai.assistant import (
    CLARIFICATION_TEXT,
    LLM_DISABLED_TEXT,
    TRANSCRIPTION_ERROR_TEXT,
    AssistantService,
)
from app.ai.llm.gigachat_client import ChatCompletion, FunctionCall
from app.ai.llm.tool_executor import ToolExecutor
from app.core.config import Settings
from app.domain.enums import EventStatus, Period, Platform
from app.repositories.event_repository import EventRepository
from app.repositories.user_repository import UserRepository
from app.services.cache.redis_service import CacheService


class FakeLLM:
    def __init__(self, *scripted: ChatCompletion) -> None:
        self.scripted = list(scripted)
        self.calls: list[dict] = []

    async def chat(self, messages, *, tools=None, temperature=None, max_tokens=None) -> ChatCompletion:
        self.calls.append({"messages": [dict(message) for message in messages], "tools": tools})
        if self.scripted:
            return self.scripted.pop(0)
        return ChatCompletion(content="Готово.")


class FakeSTT:
    def __init__(self, text: str = "позвонить Ивану") -> None:
        self.text = text
        self.calls = 0

    async def transcribe(self, wav_bytes: bytes) -> str:
        self.calls += 1
        return self.text


class FakeTTS:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def synthesize(self, text: str, *, audio_format: str | None = None) -> bytes:
        self.calls.append((text, audio_format))
        return b"opus-bytes"


class FakeConverter:
    async def to_wav(self, data: bytes, source_hint: str | None = None) -> bytes:
        return data


@pytest.fixture
def cloud_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"gigachat_credentials": "test-credentials", "sber_tts_credentials": "test-credentials"}
    )


@pytest.fixture
async def cache() -> CacheService:
    service = CacheService(enabled=True, client=FakeRedis(decode_responses=True), history_limit=50)
    yield service
    await service.close()


async def test_tool_call_round_trip_persists_event(session_factory, session, cloud_settings, cache):
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=1)
    llm = FakeLLM(
        ChatCompletion(
            content="",
            function_call=FunctionCall(
                "create_task", f'{{"title": "позвонить Ивану", "starts_at": "{start.isoformat()}"}}'
            ),
        ),
        ChatCompletion(content="Создал задачу «позвонить Ивану» на завтра в 10:00."),
    )
    assistant = AssistantService(session_factory, cloud_settings, llm=llm, cache=cache)

    response = await assistant.handle_text(Platform.WEB, "web-demo", "Напомни завтра в 10 позвонить Ивану")

    assert response.text.startswith("Создал задачу")
    assert response.intent == "create_task"
    assert len(response.events) == 1
    assert response.needs_clarification is False

    assert llm.calls[0]["tools"]
    assert llm.calls[0]["messages"][0]["role"] == "system"
    assert llm.calls[0]["messages"][-1] == {"role": "user", "content": "Напомни завтра в 10 позвонить Ивану"}
    follow_up = llm.calls[1]["messages"]
    assert follow_up[-1]["role"] == "function"
    assert follow_up[-2]["function_call"]["name"] == "create_task"
    assert "позвонить Ивану" in follow_up[-1]["content"]
    assert json.loads(follow_up[-1]["content"])["result"].startswith("Создал")

    user = await UserRepository(session).get_by_external_id(Platform.WEB, "web-demo")
    assert user is not None
    stored = await EventRepository(session).list_for_period(
        user.id, datetime.now(timezone.utc) - timedelta(days=1), datetime.now(timezone.utc) + timedelta(days=3)
    )
    assert [event.title for event in stored] == ["позвонить Ивану"]


async def test_dialogue_history_is_reused_between_requests(session_factory, cloud_settings, cache):
    llm = FakeLLM(ChatCompletion(content="Сегодня одна задача."), ChatCompletion(content="Перенёс на завтра."))
    assistant = AssistantService(session_factory, cloud_settings, llm=llm, cache=cache)

    await assistant.handle_text(Platform.WEB, "web-demo", "Что у меня сегодня?")
    await assistant.handle_text(Platform.WEB, "web-demo", "А перенеси её на завтра")

    second_request = llm.calls[1]["messages"]
    history = [message for message in second_request if message["role"] != "system"]
    assert history[0] == {"role": "user", "content": "Что у меня сегодня?"}
    assert history[1] == {"role": "assistant", "content": "Сегодня одна задача."}
    assert history[-1] == {"role": "user", "content": "А перенеси её на завтра"}


async def test_clarifying_question_is_flagged(session_factory, cloud_settings):
    llm = FakeLLM(ChatCompletion(content="На какое время поставить встречу?"))
    assistant = AssistantService(session_factory, cloud_settings, llm=llm)

    response = await assistant.handle_text(Platform.WEB, "web-demo", "Добавь встречу с командой")

    assert response.needs_clarification is True
    assert response.events == []


async def test_tool_error_without_model_answer_is_shown(session_factory, cloud_settings):
    llm = FakeLLM(
        ChatCompletion(content="", function_call=FunctionCall("create_meeting", '{"title": "с командой"}')),
        ChatCompletion(content=""),
        ChatCompletion(content=""),
        ChatCompletion(content=""),
    )
    assistant = AssistantService(session_factory, cloud_settings, llm=llm)

    response = await assistant.handle_text(Platform.WEB, "web-demo", "Добавь встречу с командой")

    assert response.text == "На какое время поставить встречу?"
    assert response.needs_clarification is True


async def test_requests_without_llm_return_configuration_hint(session_factory, settings):
    assistant = AssistantService(session_factory, settings)

    response = await assistant.handle_text(Platform.WEB, "web-demo", "Напомни завтра в 10 позвонить Ивану")

    assert response.text == LLM_DISABLED_TEXT
    assert response.events == []
    assert response.intent is None


async def test_unrelated_text_gets_clarification(session_factory, cloud_settings):
    llm = FakeLLM(ChatCompletion(content=CLARIFICATION_TEXT))
    assistant = AssistantService(session_factory, cloud_settings, llm=llm)

    response = await assistant.handle_text(Platform.WEB, "web-demo", "Привет")

    assert response.text == CLARIFICATION_TEXT
    assert response.needs_clarification is True


async def test_voice_request_returns_synthesised_answer(session_factory, cloud_settings):
    tts = FakeTTS()
    assistant = AssistantService(
        session_factory,
        cloud_settings,
        llm=FakeLLM(ChatCompletion(content="Поставил задачу.")),
        stt=FakeSTT("Поставь задачу купить билеты"),
        tts=tts,
        converter=FakeConverter(),
    )

    response = await assistant.handle_voice(Platform.TELEGRAM, "42", b"ogg-bytes", source_format="ogg")

    assert response.text == "Поставил задачу."
    assert response.audio == b"opus-bytes"
    assert response.audio_format == "opus"
    assert tts.calls and tts.calls[0][0] == response.text


async def test_empty_voice_returns_error(session_factory, settings):
    assistant = AssistantService(session_factory, settings, stt=FakeSTT())

    response = await assistant.handle_voice(Platform.TELEGRAM, "42", b"")

    assert response.text == TRANSCRIPTION_ERROR_TEXT


async def test_list_and_complete_events(session_factory, session, settings):
    user = await UserRepository(session).get_or_create(Platform.WEB, "web-demo")
    executor = ToolExecutor(session, user, settings)
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=1)
    result = await executor.execute(
        "create_task", {"title": "Купить билеты", "starts_at": start.isoformat()}
    )
    assert result.events
    await session.commit()

    assistant = AssistantService(session_factory, settings)
    events = await assistant.list_events(Platform.WEB, "web-demo", Period.ALL)
    assert [event.title for event in events] == ["Купить билеты"]

    updated = await assistant.set_event_status(Platform.WEB, "web-demo", events[0].id, EventStatus.DONE)
    assert updated.status is EventStatus.DONE

    events = await assistant.list_events(Platform.WEB, "web-demo", Period.ALL)
    assert events[0].status is EventStatus.DONE


async def test_llm_failure_after_tool_call_keeps_the_created_event(session_factory, session, cloud_settings):
    from app.core.exceptions import LLMError

    class FailingLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def chat(self, messages, **kwargs) -> ChatCompletion:
            self.calls += 1
            if self.calls == 1:
                return ChatCompletion(
                    content="", function_call=FunctionCall("create_task", '{"title": "позвонить Ивану"}')
                )
            raise LLMError("gigachat is unavailable")

    llm = FailingLLM()
    assistant = AssistantService(session_factory, cloud_settings, llm=llm)

    response = await assistant.handle_text(Platform.WEB, "web-demo", "Напомни позвонить Ивану")

    assert "Создал задачу" in response.text
    assert response.text != "Не получилось обработать запрос. Попробуйте ещё раз."
    user = await UserRepository(session).get_by_external_id(Platform.WEB, "web-demo")
    assert user is not None
    stored = await EventRepository(session).search(user.id, "Ивану")
    assert len(stored) == 1


async def test_empty_completion_is_not_retried(session_factory, cloud_settings):
    llm = FakeLLM(ChatCompletion(content=""), ChatCompletion(content=""), ChatCompletion(content=""))
    assistant = AssistantService(session_factory, cloud_settings, llm=llm)

    response = await assistant.handle_text(Platform.WEB, "web-demo", "Привет")

    assert len(llm.calls) == 1
    assert response.text == CLARIFICATION_TEXT


async def test_telegram_voice_is_always_opus(session_factory, settings):
    tts = FakeTTS()
    settings = settings.model_copy(update={"sber_tts_credentials": "test-credentials", "sber_tts_format": "wav16"})
    assistant = AssistantService(
        session_factory,
        settings,
        llm=FakeLLM(ChatCompletion(content="Поставил задачу.")),
        stt=FakeSTT("Поставь задачу купить билеты"),
        tts=tts,
        converter=FakeConverter(),
    )

    response = await assistant.handle_voice(Platform.TELEGRAM, "42", b"ogg-bytes")

    assert response.audio_format == "opus"
    assert tts.calls[0][1] == "opus"


async def test_web_voice_normalises_wav16_format(session_factory, settings):
    tts = FakeTTS()
    settings = settings.model_copy(update={"sber_tts_credentials": "test-credentials", "sber_tts_format": "wav16"})
    assistant = AssistantService(
        session_factory,
        settings,
        llm=FakeLLM(ChatCompletion(content="Поставил задачу.")),
        stt=FakeSTT("Поставь задачу купить билеты"),
        tts=tts,
        converter=FakeConverter(),
    )

    response = await assistant.handle_voice(Platform.WEB, "web-demo", b"webm-bytes")

    assert response.audio_format == "wav"
    assert response.audio_mime_type == "audio/wav"
