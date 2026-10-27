from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.user import User
from app.domain.enums import EventType, Platform
from app.domain.models import EventCreate
from app.repositories.event_repository import EventRepository
from app.repositories.user_repository import UserRepository
from app.services.scheduler.reminder_service import ReminderService

NOW = datetime.now(timezone.utc).replace(microsecond=0)


async def test_due_reminder_is_delivered_and_marked(session_factory, session):
    user = await UserRepository(session).get_or_create(Platform.TELEGRAM, "42")
    await EventRepository(session).create(
        user.id,
        EventCreate(
            type=EventType.REMINDER,
            title="Позвонить Ивану",
            starts_at=NOW - timedelta(minutes=1),
            remind_at=NOW - timedelta(minutes=1),
        ),
    )

    service = ReminderService(session_factory, poll_interval_seconds=1)
    delivered: list[tuple[str, str]] = []

    async def notifier(notified_user: User, event) -> None:
        delivered.append((notified_user.external_id, event.title))

    service.register_notifier(Platform.TELEGRAM, notifier)

    assert await service.run_once() == 1
    assert delivered == [("42", "Позвонить Ивану")]
    assert await service.run_once() == 0


async def test_foreign_platform_reminders_do_not_fill_the_queue(session_factory, session):
    web_user = await UserRepository(session).get_or_create(Platform.WEB, "web-1")
    telegram_user = await UserRepository(session).get_or_create(Platform.TELEGRAM, "42")
    repository = EventRepository(session)
    await repository.create(
        web_user.id, EventCreate(type=EventType.REMINDER, title="Веб", remind_at=NOW - timedelta(minutes=3))
    )
    await repository.create(
        telegram_user.id,
        EventCreate(type=EventType.REMINDER, title="Телеграм", remind_at=NOW - timedelta(minutes=1)),
    )

    service = ReminderService(session_factory, poll_interval_seconds=1)
    delivered: list[str] = []

    async def notifier(notified_user: User, event) -> None:
        delivered.append(event.title)

    service.register_notifier(Platform.TELEGRAM, notifier)

    assert await service.run_once() == 1
    assert delivered == ["Телеграм"]

    web_event = await repository.search(web_user.id, "Веб")
    assert web_event[0].reminder_sent_at is None


async def test_reminder_without_notifier_stays_in_queue(session_factory, session):
    user = await UserRepository(session).get_or_create(Platform.MAX, "777")
    event = await EventRepository(session).create(
        user.id,
        EventCreate(type=EventType.REMINDER, title="Проверить почту", remind_at=NOW - timedelta(minutes=2)),
    )

    service = ReminderService(session_factory, poll_interval_seconds=1)
    assert await service.run_once() == 0

    stored = await EventRepository(session).get_for_user(user.id, event.id)
    assert stored is not None
    assert stored.reminder_sent_at is None


async def test_start_and_stop_are_idempotent(session_factory):
    service = ReminderService(session_factory, poll_interval_seconds=1)

    await service.start()
    await service.start()
    await service.stop()
    await service.stop()


@pytest.mark.parametrize("remind_in", [timedelta(minutes=-2), timedelta(seconds=10)])
async def test_lookahead_window(session_factory, session, remind_in):
    user = await UserRepository(session).get_or_create(Platform.WEB, "web-demo")
    await EventRepository(session).create(
        user.id,
        EventCreate(type=EventType.REMINDER, title="Скоро", remind_at=NOW + remind_in),
    )

    service = ReminderService(session_factory, poll_interval_seconds=1, lookahead_seconds=60)
    delivered: list[str] = []

    async def notifier(notified_user: User, event) -> None:
        delivered.append(event.title)

    service.register_notifier(Platform.WEB, notifier)
    assert await service.run_once() == 1
    assert delivered == ["Скоро"]


async def test_linked_platform_reminder_is_delivered(session_factory, session):
    from app.db.models.account_link import AccountLink

    web_user = await UserRepository(session).get_or_create(Platform.WEB, "web-primary")
    session.add(AccountLink(user_id=web_user.id, platform=Platform.TELEGRAM, external_id="tg-linked-999"))
    await session.commit()

    await EventRepository(session).create(
        web_user.id,
        EventCreate(type=EventType.REMINDER, title="Напомни в Телеграм", remind_at=NOW - timedelta(minutes=1)),
    )

    service = ReminderService(session_factory, poll_interval_seconds=1)
    delivered: list[tuple[str, str, str]] = []

    async def telegram_notifier(notified_user: User, event) -> None:
        delivered.append((notified_user.platform.value, notified_user.external_id, event.title))

    service.register_notifier(Platform.TELEGRAM, telegram_notifier)

    assert await service.run_once() == 1
    assert delivered == [("telegram", "tg-linked-999", "Напомни в Телеграм")]
    assert await service.run_once() == 0

