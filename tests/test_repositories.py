from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.user import User
from app.domain.enums import EventStatus, EventType, Platform
from app.domain.models import EventCreate, EventUpdate
from app.repositories.event_repository import EventRepository
from app.repositories.user_repository import UserRepository

MOSCOW = timezone(timedelta(hours=3))
NOW = datetime(2025, 3, 3, 10, 0, tzinfo=MOSCOW)


@pytest.fixture
async def user(session) -> User:
    return await UserRepository(session).get_or_create(Platform.TELEGRAM, "42", username="tester")


async def test_user_get_or_create_is_idempotent(session, user):
    again = await UserRepository(session).get_or_create(Platform.TELEGRAM, "42", username="renamed")
    assert again.id == user.id
    assert again.username == "renamed"


async def test_user_platforms_are_separate(session, user):
    web_user = await UserRepository(session).get_or_create(Platform.WEB, "42")
    assert web_user.id != user.id


async def test_list_for_period_filters_by_day(session, user):
    repository = EventRepository(session)
    today_event = await repository.create(
        user.id,
        EventCreate(type=EventType.TASK, title="Сегодня", starts_at=NOW + timedelta(hours=2)),
    )
    tomorrow_event = await repository.create(
        user.id,
        EventCreate(type=EventType.MEETING, title="Завтра", starts_at=NOW + timedelta(days=1)),
    )

    start = datetime(2025, 3, 3, 0, 0, tzinfo=MOSCOW)
    today = await repository.list_for_period(user.id, start, start + timedelta(days=1))
    assert [event.id for event in today] == [today_event.id]

    tomorrow_start = start + timedelta(days=1)
    tomorrow = await repository.list_for_period(user.id, tomorrow_start, tomorrow_start + timedelta(days=1))
    assert [event.id for event in tomorrow] == [tomorrow_event.id]


async def test_list_for_period_filters_types_and_status(session, user):
    repository = EventRepository(session)
    meeting = await repository.create(
        user.id, EventCreate(type=EventType.MEETING, title="Созвон", starts_at=NOW)
    )
    done_task = await repository.create(
        user.id, EventCreate(type=EventType.TASK, title="Сделано", starts_at=NOW)
    )
    await repository.mark_done(done_task)

    only_meetings = await repository.list_for_period(
        user.id, NOW - timedelta(days=1), NOW + timedelta(days=1), types=[EventType.MEETING]
    )
    assert [event.id for event in only_meetings] == [meeting.id]

    pending = await repository.list_for_period(
        user.id, NOW - timedelta(days=1), NOW + timedelta(days=1), include_done=False
    )
    assert [event.id for event in pending] == [meeting.id]


async def test_search_matches_inflected_russian_words(session, user):
    repository = EventRepository(session)
    await repository.create(
        user.id,
        EventCreate(
            type=EventType.TASK,
            title="Подготовить презентацию для клиента",
            description="Слайды и смета",
            starts_at=NOW,
        ),
    )
    await repository.create(user.id, EventCreate(type=EventType.MEETING, title="Встреча с Иваном", starts_at=NOW))

    by_noun = await repository.search(user.id, "презентацию")
    assert [event.title for event in by_noun] == ["Подготовить презентацию для клиента"]

    by_name = await repository.search(user.id, "Иван")
    assert [event.title for event in by_name] == ["Встреча с Иваном"]

    by_description = await repository.search(user.id, "смета")
    assert len(by_description) == 1


async def test_search_ignores_stopwords_and_cancelled(session, user):
    repository = EventRepository(session)
    event = await repository.create(user.id, EventCreate(type=EventType.TASK, title="Позвонить Ивану"))
    await repository.update(event, EventUpdate(status=EventStatus.CANCELLED))

    assert await repository.search(user.id, "найди задачу про Ивана") == []
    assert await repository.search(user.id, "и") == []


async def test_search_by_type_word_returns_nearest_records(session, user):
    repository = EventRepository(session)
    now = datetime.now(MOSCOW)
    past = await repository.create(
        user.id, EventCreate(type=EventType.MEETING, title="Планёрка вчера", starts_at=now - timedelta(days=1))
    )
    soon = await repository.create(
        user.id, EventCreate(type=EventType.MEETING, title="Встреча с Иваном", starts_at=now + timedelta(hours=1))
    )
    later = await repository.create(
        user.id, EventCreate(type=EventType.MEETING, title="Созвон по релизу", starts_at=now + timedelta(days=2))
    )
    undated = await repository.create(user.id, EventCreate(type=EventType.MEETING, title="Встреча без даты"))
    await repository.create(user.id, EventCreate(type=EventType.TASK, title="Проверить отчёт", starts_at=now))

    found = await repository.search(user.id, "покажи встречи")
    assert [event.id for event in found] == [soon.id, later.id, past.id, undated.id]
    assert [event.id for event in await repository.search(user.id, "встречи", limit=2)] == [soon.id, later.id]
    assert [event.title for event in await repository.search(user.id, "задачи")] == ["Проверить отчёт"]
    assert await repository.search(user.id, "напоминания") == []
    # значимое слово рядом со словом типа по-прежнему ищет по названию, а не по одному типу
    assert [event.title for event in await repository.search(user.id, "найди встречу с Иваном")] == ["Встреча с Иваном"]


async def test_search_without_type_or_keywords_returns_nothing(session, user):
    repository = EventRepository(session)
    await repository.create(user.id, EventCreate(type=EventType.TASK, title="Позвонить Ивану", starts_at=NOW))

    assert await repository.search(user.id, "записи") == []
    assert await repository.search(user.id, "") == []


async def test_due_reminders_are_delivered_once(session, user):
    repository = EventRepository(session)
    event = await repository.create(
        user.id,
        EventCreate(
            type=EventType.REMINDER,
            title="Позвонить",
            starts_at=NOW,
            remind_at=NOW - timedelta(minutes=1),
        ),
    )
    await repository.create(
        user.id,
        EventCreate(type=EventType.REMINDER, title="Позже", remind_at=NOW + timedelta(hours=5)),
    )

    due = await repository.due_reminders(now=NOW)
    assert [item.id for item in due] == [event.id]
    assert due[0].user.external_id == "42"

    await repository.mark_reminder_sent(event)
    assert await repository.due_reminders(now=NOW) == []


async def test_update_and_mark_done(session, user):
    repository = EventRepository(session)
    event = await repository.create(user.id, EventCreate(type=EventType.TASK, title="Черновик"))

    updated = await repository.update(event, EventUpdate(title="Финальный", starts_at=NOW))
    assert updated.title == "Финальный"
    assert updated.starts_at == NOW.replace(tzinfo=None) - timedelta(hours=3)

    done = await repository.mark_done(updated)
    assert done.status is EventStatus.DONE

    back = await repository.mark_done(done, done=False)
    assert back.status is EventStatus.PENDING


async def test_rescheduled_reminder_becomes_due_again(session, user):
    repository = EventRepository(session)
    event = await repository.create(
        user.id,
        EventCreate(type=EventType.REMINDER, title="Позвонить", remind_at=NOW - timedelta(minutes=1)),
    )
    await repository.mark_reminder_sent(event)
    assert await repository.due_reminders(now=NOW) == []

    await repository.update(event, EventUpdate(remind_at=NOW - timedelta(seconds=10)))
    assert [item.id for item in await repository.due_reminders(now=NOW)] == [event.id]

    sent = (await repository.due_reminders(now=NOW))[0]
    await repository.mark_reminder_sent(sent)
    await repository.mark_done(sent, done=False)
    assert [item.id for item in await repository.due_reminders(now=NOW)] == [event.id]


async def test_due_reminders_can_be_limited_by_platform(session, user):
    repository = EventRepository(session)
    web_user = await UserRepository(session).get_or_create(Platform.WEB, "web-1")
    web_event = await repository.create(
        web_user.id, EventCreate(type=EventType.REMINDER, title="Веб", remind_at=NOW - timedelta(minutes=2))
    )
    telegram_event = await repository.create(
        user.id, EventCreate(type=EventType.REMINDER, title="Телеграм", remind_at=NOW - timedelta(minutes=2))
    )

    due = await repository.due_reminders(now=NOW, platforms=[Platform.TELEGRAM])
    assert [item.id for item in due] == [telegram_event.id]
    assert web_event.id not in {item.id for item in due}


async def test_search_handles_intent_and_recurrence_phrasing(session, user):
    repository = EventRepository(session)
    event = await repository.create(
        user.id,
        EventCreate(
            type=EventType.REMINDER,
            title="поесть",
            starts_at=NOW,
            rrule="FREQ=WEEKLY;BYDAY=TU",
            status=EventStatus.PENDING,
        ),
    )

    found1 = await repository.search(user.id, "поесть каждый вторник")
    assert len(found1) == 1
    assert found1[0].id == event.id

    found2 = await repository.search(user.id, "удали напоминание поесть каждый вторник")
    assert len(found2) == 1
    assert found2[0].id == event.id

    found3 = await repository.search(user.id, "поесть")
    assert len(found3) == 1
    assert found3[0].id == event.id

