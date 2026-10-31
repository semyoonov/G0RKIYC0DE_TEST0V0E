"""The assistant must not invent times, lose actions or echo tool calls."""

from datetime import datetime, timedelta, timezone

import pytest

from app.ai.assistant import AssistantService, _humanize
from app.ai.llm.gigachat_client import ChatCompletion
from app.ai.llm.tool_executor import ToolExecutor
from app.domain.enums import EventType, Platform
from app.domain.models import EventCreate
from app.repositories.event_repository import EventRepository
from app.repositories.user_repository import UserRepository

MOSCOW = timezone(timedelta(hours=3))


class ScriptedLLM:
    def __init__(self, *scripted: ChatCompletion) -> None:
        self.scripted = list(scripted)
        self.calls: list[list[dict]] = []

    async def chat(self, messages, *, tools=None, temperature=None, max_tokens=None) -> ChatCompletion:
        self.calls.append([dict(message) for message in messages])
        if self.scripted:
            return self.scripted.pop(0)
        return ChatCompletion(content="Готово.")


@pytest.fixture
async def user(session):
    return await UserRepository(session).get_or_create(Platform.WEB, "web-reliability")


@pytest.mark.parametrize("utterance", ["Поставь встречу с Иваном завтра", "Встреча с командой"])
async def test_meeting_without_a_time_asks_instead_of_inventing_one(session, user, settings, utterance):
    executor = ToolExecutor(session, user, settings, None, utterance=utterance)

    result = await executor.execute(
        "create_meeting",
        {"title": "с Иваном", "starts_at": "2026-11-01T10:00:00+03:00"},
    )

    assert result.failed
    assert "время" in result.content
    assert result.events == []


async def test_meeting_gets_the_weekday_the_user_said_not_the_model(session, user, settings):
    executor = ToolExecutor(
        session, user, settings, None, utterance="В четверг в 11 у меня встреча с дизайнером"
    )

    result = await executor.execute(
        "create_meeting",
        {"title": "с дизайнером", "starts_at": "2026-11-02T11:00:00+03:00"},  # model said Monday
    )

    assert not result.failed
    stored = result.events[0].starts_at.astimezone(MOSCOW)
    assert stored.weekday() == 3  # Thursday
    assert stored.hour == 11


async def test_task_keeps_the_named_weekday_and_invents_no_clock_time(session, user, settings):
    executor = ToolExecutor(session, user, settings, None, utterance="В пятницу нужно отправить отчет")

    result = await executor.execute(
        "create_task",
        {"title": "отправить отчет", "starts_at": "2026-11-03T19:00:00+03:00"},  # model invented Tue 19:00
    )

    assert not result.failed
    stored = result.events[0].starts_at.astimezone(MOSCOW)
    assert stored.weekday() == 4  # Friday
    assert (stored.hour, stored.minute) == (23, 59)  # end of that day, not the invented 19:00
    assert "время не указано" in result.content


async def test_reminder_without_a_time_is_not_created(session, user, settings):
    executor = ToolExecutor(session, user, settings, None, utterance="Напомни позвонить Ивану")

    result = await executor.execute("create_task", {"title": "позвонить Ивану", "is_reminder": True})

    assert result.failed
    assert result.events == []


async def test_leaked_tool_call_is_executed_and_removed_from_the_reply(session, user, settings):
    leaked = (
        "create_meeting [\n"
        '    "starts_at": "2026-11-01T15:00:00+03:00",\n'
        '    "title": "с командой"\n'
        "] Встреча с командой запланирована на завтра в 15:00."
    )
    llm = ScriptedLLM(
        ChatCompletion(content=leaked, finish_reason="stop"),
        ChatCompletion(content="Встреча «с командой» создана на завтра в 15:00.", finish_reason="stop"),
    )
    service = AssistantService(
        session_factory=_factory(session), settings=settings, llm=llm
    )

    response = await service.handle_text(Platform.WEB, "web-leak", "Добавь встречу с командой завтра в 15:00")

    assert "create_meeting" not in response.text
    assert "<|superquote|>" not in response.text
    assert response.events and response.events[0].type is EventType.MEETING
    expected_day = (datetime.now(MOSCOW) + timedelta(days=1)).date()
    assert response.events[0].starts_at.astimezone(MOSCOW).date() == expected_day


class RecordingCache:
    def __init__(self) -> None:
        self.stored: list[dict] = []

    async def get_history(self, key, limit):
        return list(self.stored)

    async def push_history(self, key, entry, limit):
        self.stored.append(dict(entry))


async def test_history_never_stores_call_syntax(session, user, settings):
    cache = RecordingCache()
    leaked = 'list_events [ "period": "today" ] Сегодня пусто.'
    llm = ScriptedLLM(
        ChatCompletion(content=leaked, finish_reason="stop"),
        ChatCompletion(content="Сегодня ничего не запланировано.", finish_reason="stop"),
    )
    service = AssistantService(session_factory=_factory(session), settings=settings, llm=llm, cache=cache)

    await service.handle_text(Platform.WEB, "web-history", "Что у меня сегодня?")

    stored_text = " ".join(str(entry) for entry in cache.stored)
    assert "list_events" not in stored_text
    assert "<|superquote|>" not in stored_text


async def test_off_topic_request_is_refused_without_calling_the_model(settings):
    llm = ScriptedLLM()
    service = AssistantService(session_factory=None, settings=settings, llm=llm)

    response = await service.handle_text(Platform.WEB, "web-scope", "Дай рецепт пирога")

    assert "только с задачами" in response.text
    assert llm.calls == []


async def test_dated_task_is_not_turned_into_a_reminder(session, user, settings):
    executor = ToolExecutor(
        session, user, settings, None, utterance="В пятницу нужно отправить отчет"
    )

    result = await executor.execute(
        "create_task", {"title": "отправить отчет", "is_reminder": True}
    )

    assert not result.failed
    assert result.events[0].type is EventType.TASK


async def test_search_prefers_the_nearer_record_when_names_tie(session, user):
    repository = EventRepository(session)
    now = datetime.now(MOSCOW)
    await repository.create(
        user.id,
        EventCreate(type=EventType.MEETING, title="встреча с командой", starts_at=now + timedelta(days=1)),
    )
    await repository.create(
        user.id,
        EventCreate(type=EventType.MEETING, title="Планёрка команды", starts_at=now + timedelta(days=21)),
    )

    found = await repository.search(user.id, "перенеси встречу с командой на 18:00", limit=3)

    assert found and found[0].title == "встреча с командой"


def test_humanize_strips_leaked_syntax():
    assert _humanize('search_events [ "query": "отчет" ] Нашёл задачу.') == "Нашёл задачу."


def _factory(session):
    """A session factory that hands out the test session, mirroring app wiring."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def factory():
        yield session

    return factory
