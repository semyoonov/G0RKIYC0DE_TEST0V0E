from datetime import datetime, timedelta, timezone

import pytest
from fakeredis.aioredis import FakeRedis

from app.ai.llm.tool_executor import ToolExecutor
from app.db.models.user import User
from app.domain.enums import EventStatus, EventType, Platform
from app.domain.models import EventCreate
from app.repositories.event_repository import EventRepository
from app.repositories.user_repository import UserRepository
from app.services.cache.redis_service import CacheService

MOSCOW = timezone(timedelta(hours=3))
NOW = datetime.now(MOSCOW).replace(microsecond=0)


@pytest.fixture
async def user(session) -> User:
    return await UserRepository(session).get_or_create(Platform.WEB, "web-demo")


@pytest.fixture
async def cache() -> CacheService:
    service = CacheService(enabled=True, client=FakeRedis(decode_responses=True))
    yield service
    await service.close()


@pytest.fixture
async def executor(session, user, settings, cache) -> ToolExecutor:
    return ToolExecutor(session, user, settings, cache)


async def test_create_task_stores_event_and_confirms(executor, session, user):
    start = NOW + timedelta(days=1)
    result = await executor.execute(
        "create_task",
        {"title": "позвонить Ивану", "starts_at": start.isoformat(), "is_reminder": True},
    )

    assert not result.failed
    assert "Создал напоминание" in result.content
    assert len(result.events) == 1
    event = result.events[0]
    assert event.type is EventType.REMINDER
    assert event.title == "позвонить Ивану"
    assert event.starts_at == start
    assert event.remind_at == start

    stored = await EventRepository(session).get_for_user(user.id, event.id)
    assert stored is not None
    assert stored.source is Platform.WEB


async def test_create_meeting_requires_time(executor):
    result = await executor.execute("create_meeting", {"title": "с командой"})

    assert result.failed
    assert result.content.startswith("ОШИБКА:")
    assert "время" in result.content


async def test_create_meeting_requires_title(executor):
    start = NOW + timedelta(days=1)
    result_none = await executor.execute("create_meeting", {"starts_at": start.isoformat()})
    assert result_none.failed
    assert "как назвать" in result_none.content

    result_generic = await executor.execute("create_meeting", {"title": "Встреча", "starts_at": start.isoformat()})
    assert result_generic.failed
    assert "как назвать" in result_generic.content


async def test_create_meeting_warns_about_conflict(executor):
    start = NOW + timedelta(days=2)
    await executor.execute("create_meeting", {"title": "с командой", "starts_at": start.isoformat()})

    result = await executor.execute("create_meeting", {"title": "с дизайнером", "starts_at": start.isoformat()})
    assert "уже стоит" in result.content


async def test_list_events_is_cached_until_a_write(executor, session, user):
    start = NOW + timedelta(minutes=5)
    created = await executor.execute("create_task", {"title": "отправить отчёт", "starts_at": start.isoformat()})
    first = await executor.execute("list_events", {"period": "all"})
    assert created.events[0].title in first.content

    await EventRepository(session).create(
        user.id,
        EventCreate(type=EventType.TASK, title="мимо кэша", starts_at=start + timedelta(minutes=1)),
    )
    second = await executor.execute("list_events", {"period": "all"})
    assert second.content == first.content

    await executor.execute(
        "create_task", {"title": "через ассистента", "starts_at": start + timedelta(minutes=2)}
    )
    third = await executor.execute("list_events", {"period": "all"})
    assert "через ассистента" in third.content
    assert "мимо кэша" in third.content


async def test_search_events_returns_titles_with_ids(executor):
    await executor.execute("create_task", {"title": "подготовить презентацию", "starts_at": NOW.isoformat()})

    result = await executor.execute("search_events", {"query": "презентация"})
    assert not result.failed
    assert "Нашёл 1" in result.content
    assert "подготовить презентацию" in result.content
    assert "id " in result.content


async def test_update_complete_and_delete(executor, session, user):
    created = await executor.execute("create_task", {"title": "черновик"})
    event_id = created.events[0].id

    updated = await executor.execute("update_event", {"event_id": event_id, "title": "финальный отчёт"})
    assert "финальный отчёт" in updated.content

    completed = await executor.execute("complete_event", {"event_id": event_id})
    assert "Отметил как выполнено" in completed.content
    assert completed.events[0].status is EventStatus.DONE

    deleted = await executor.execute("delete_event", {"event_id": event_id})
    assert "Удалил" in deleted.content
    assert await EventRepository(session).get_for_user(user.id, event_id) is None


async def test_unknown_tool_and_missing_event(executor):
    unknown = await executor.execute("drop_database", {})
    assert unknown.failed

    missing = await executor.execute("complete_event", {"event_id": 999})
    assert missing.failed
    assert "не найдена" in missing.content


async def test_arguments_may_arrive_as_json_string(executor):
    result = await executor.execute("create_task", '{"title": "купить билеты", "is_reminder": false}')
    assert not result.failed
    assert result.events[0].title == "купить билеты"


async def test_parse_datetime_accepts_common_formats():
    from app.ai.llm.tool_executor import parse_datetime

    tz = MOSCOW
    assert parse_datetime("2025-03-05T10:00:00+03:00", tz) == datetime(2025, 3, 5, 10, 0, tzinfo=tz)
    assert parse_datetime("2025-03-05 10:00", tz) == datetime(2025, 3, 5, 10, 0, tzinfo=tz)
    assert parse_datetime("2025-03-05", tz) == datetime(2025, 3, 5, 0, 0, tzinfo=tz)
    assert parse_datetime("", tz) is None
    assert parse_datetime("не дата", tz) is None


def test_weekday_time_is_rendered_in_accusative():
    from app.core.timeutils import format_datetime

    friday = datetime(2025, 3, 7, 9, 0, tzinfo=MOSCOW)
    monday = datetime(2025, 3, 3, 10, 0, tzinfo=MOSCOW)
    assert format_datetime(friday, MOSCOW, now=monday) == "в пятницу в 09:00"


async def test_confirmation_has_no_dangling_preposition(executor):
    start = NOW + timedelta(days=1)
    result = await executor.execute("create_task", {"title": "отправить отчёт", "starts_at": start.isoformat()})
    assert " — завтра в " in result.content
    assert " на завтра" not in result.content
