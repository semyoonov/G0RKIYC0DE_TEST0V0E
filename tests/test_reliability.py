"""The assistant must not invent times, lose actions or echo tool calls."""

import json
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.ai.assistant import AssistantService, _humanize
from app.ai.llm.gigachat_client import ChatCompletion
from app.ai.llm.temporal import (
    TemporalFacts,
    facts_from_payload,
    moment_from_facts,
    weekday_date,
)
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


class FactsLLM:
    """Stands in for the narrow extraction call."""

    def __init__(self, **facts) -> None:
        self.facts = facts
        self.calls = 0

    async def chat(self, messages, **kwargs) -> ChatCompletion:
        self.calls += 1
        return ChatCompletion(content=json.dumps(self.facts, ensure_ascii=False))


class RecordingCache:
    def __init__(self) -> None:
        self.stored: list[dict] = []

    async def get_history(self, key, limit):
        return list(self.stored)

    async def push_history(self, key, entry, limit):
        self.stored.append(dict(entry))


@pytest.fixture
async def user(session):
    return await UserRepository(session).get_or_create(Platform.WEB, "web-reliability")


async def test_meeting_without_a_named_time_asks_instead_of_inventing_one(session, user, settings):
    llm = FactsLLM(has_date=True, date="2026-11-01", has_time=False, time=None)
    executor = ToolExecutor(session, user, settings, None, llm=llm, utterance="Поставь встречу с Иваном завтра")

    result = await executor.execute(
        "create_meeting",
        {"title": "с Иваном", "starts_at": "2026-11-01T10:00:00+03:00"},
    )

    assert result.failed
    assert "время" in result.content
    assert result.events == []


async def test_meeting_lands_on_the_weekday_the_extraction_reported(session, user, settings):
    llm = FactsLLM(has_date=False, date=None, has_time=True, time="11:00", weekday="четверг")
    executor = ToolExecutor(
        session, user, settings, None, llm=llm, utterance="В четверг в 11 у меня встреча с дизайнером"
    )

    # The chat model proposed Monday; the extraction says Thursday.
    result = await executor.execute(
        "create_meeting",
        {"title": "с дизайнером", "starts_at": "2026-11-02T11:00:00+03:00"},
    )

    assert not result.failed
    stored = result.events[0].starts_at.astimezone(MOSCOW)
    assert stored.weekday() == 3
    assert stored.hour == 11


async def test_task_with_a_named_day_keeps_no_invented_clock_time(session, user, settings):
    llm = FactsLLM(has_date=True, date=None, has_time=False, time=None, weekday="пятница")
    executor = ToolExecutor(session, user, settings, None, llm=llm, utterance="В пятницу нужно отправить отчет")

    result = await executor.execute(
        "create_task",
        {"title": "отправить отчет", "starts_at": "2026-11-03T19:00:00+03:00"},  # model invented Tuesday 19:00
    )

    assert not result.failed
    stored = result.events[0].starts_at.astimezone(MOSCOW)
    assert stored.weekday() == 4
    assert (stored.hour, stored.minute) == (23, 59)
    assert "время не указано" in result.content


async def test_reminder_without_a_named_time_is_not_created(session, user, settings):
    llm = FactsLLM(has_date=False, date=None, has_time=False, time=None)
    executor = ToolExecutor(session, user, settings, None, llm=llm, utterance="Напомни позвонить Ивану")

    result = await executor.execute(
        "create_task",
        {"title": "позвонить Ивану", "is_reminder": True},
    )

    assert result.failed
    assert result.events == []


async def test_list_reply_is_compact_and_free_of_descriptions(session, user, settings):
    repository = EventRepository(session)
    now = datetime.now(MOSCOW)
    await repository.create(
        user.id,
        EventCreate(
            type=EventType.MEETING,
            title="встреча с командой",
            description="Обсудить спринт и релиз",
            starts_at=now + timedelta(hours=2),
        ),
    )
    await repository.create(
        user.id,
        EventCreate(type=EventType.TASK, title="проверить отчёт", starts_at=now + timedelta(hours=3)),
    )
    executor = ToolExecutor(session, user, settings, None)

    result = await executor.execute("list_events", {"period": "today"})

    assert not result.failed
    assert "Обсудить спринт" not in result.content
    assert "; " in result.content


async def test_update_by_query_takes_the_record_the_user_named(session, user, settings):
    now = datetime.now(MOSCOW)
    repository = EventRepository(session)
    target = await repository.create(
        user.id,
        EventCreate(type=EventType.MEETING, title="встреча с командой", starts_at=now + timedelta(days=1)),
    )
    await repository.create(
        user.id,
        EventCreate(type=EventType.MEETING, title="Планёрка команды", starts_at=now + timedelta(days=21)),
    )
    executor = ToolExecutor(session, user, settings, None)

    result = await executor.execute(
        "update_event",
        {"query": "встреча с командой", "starts_at": "2026-11-01T18:00:00+03:00"},
    )

    assert not result.failed
    assert result.events[0].id == target.id
    assert result.events[0].starts_at.astimezone(MOSCOW).hour == 18


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
    service = AssistantService(session_factory=_factory(session), settings=settings, llm=llm)

    response = await service.handle_text(Platform.WEB, "web-leak", "Добавь встречу с командой завтра в 15:00")

    assert "create_meeting" not in response.text
    assert "<|superquote|>" not in response.text
    assert response.events and response.events[0].type is EventType.MEETING


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


def test_humanize_strips_leaked_syntax():
    assert _humanize('search_events [ "query": "отчет" ] Нашёл задачу.') == "Нашёл задачу."


def _factory(session):
    """A session factory that hands out the test session, mirroring app wiring."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def factory():
        yield session

    return factory


def test_weekday_date_is_the_next_occurrence():
    today = date(2026, 10, 31)  # Saturday

    assert weekday_date("четверг", today) == date(2026, 11, 5)
    assert weekday_date("суббота", today) == date(2026, 10, 31)
    assert weekday_date("не день", today) is None


def test_moment_from_facts_keeps_the_day_for_a_bare_time():
    now = datetime(2026, 10, 31, 19, 8, tzinfo=MOSCOW)
    facts = facts_from_payload({"has_date": False, "has_time": True, "time": "18:00"})

    moment = moment_from_facts(facts, datetime(2026, 11, 5, 9, 0, tzinfo=MOSCOW), now=now)

    assert moment == datetime(2026, 11, 5, 18, 0, tzinfo=MOSCOW)


def test_moment_from_facts_uses_the_weekday_when_no_date_was_given():
    now = datetime(2026, 10, 31, 19, 8, tzinfo=MOSCOW)
    facts = TemporalFacts(has_time=True, time=time(11, 0), weekday="четверг")

    moment = moment_from_facts(facts, None, now=now)

    assert moment == datetime(2026, 11, 5, 11, 0, tzinfo=MOSCOW)


def test_facts_from_payload_ignores_unknown_weekday():
    facts = facts_from_payload({"weekday": "лунный день", "has_date": True, "date": "2026-11-06"})

    assert facts.weekday is None
    assert facts.date == date(2026, 11, 6)
