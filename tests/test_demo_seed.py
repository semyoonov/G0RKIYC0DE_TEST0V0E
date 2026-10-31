from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.ai.llm.gigachat_client import ChatCompletion
from app.ai.assistant import AssistantService
from app.db.models.event import Event
from app.db.models.user import User
from app.domain.enums import EventStatus, EventType, Platform
from app.domain.identity import Identity
from app.repositories.account_repository import AccountRepository
from app.services.auth.service import AuthService
from app.services.demo_seed import DEMO_EVENTS, seed_demo_events
from test_auth_service import auth_settings


class SilentLLM:
    async def chat(self, messages, *, tools=None, temperature=None, max_tokens=None) -> ChatCompletion:
        return ChatCompletion(content="Готово.")


async def events_of(session_factory, user_id: int) -> list[Event]:
    async with session_factory() as session:
        return list(
            (
                await session.execute(
                    select(Event).where(Event.user_id == user_id).order_by(Event.starts_at, Event.id)
                )
            )
            .scalars()
            .all()
        )


def test_demo_events_are_future_dated_and_varied() -> None:
    kinds = {event.type for event in DEMO_EVENTS}

    assert kinds == {EventType.MEETING, EventType.TASK, EventType.REMINDER}
    assert any(event.repeat_weekly for event in DEMO_EVENTS)
    assert any(event.hour is None for event in DEMO_EVENTS)
    assert all(event.in_days >= 0 for event in DEMO_EVENTS)


async def test_seed_writes_every_blueprint_ahead_of_now(session_factory, session) -> None:
    user = User(platform=Platform.WEB, external_id="seed-target", timezone="Europe/Moscow")
    session.add(user)
    await session.flush()

    created = await seed_demo_events(session, user, "Europe/Moscow")
    await session.commit()

    assert created == len(DEMO_EVENTS)
    stored = await events_of(session_factory, user.id)
    assert len(stored) == len(DEMO_EVENTS)
    assert {event.status for event in stored} == {EventStatus.PENDING}
    moment = datetime.now(timezone.utc)
    dated = [event for event in stored if event.starts_at is not None]
    assert dated
    assert all(event.starts_at.replace(tzinfo=timezone.utc) > moment for event in dated)
    reminders = [event for event in stored if event.type is EventType.REMINDER]
    assert reminders and all(event.remind_at is not None for event in reminders)
    recurring = [event for event in stored if event.rrule]
    assert len(recurring) == 1
    assert recurring[0].rrule.startswith("FREQ=WEEKLY;BYDAY=")


async def test_new_account_gets_examples_once(session_factory) -> None:
    seen: list[int] = []

    async def hook(session, user) -> None:
        seen.append(user.id)
        await seed_demo_events(session, user, "Europe/Moscow")

    async with session_factory() as session:
        repository = AccountRepository(session, on_created=hook)
        user = await repository.resolve(Identity(Platform.WEB, "kept-once"))
        repeated = await repository.resolve(Identity(Platform.WEB, "kept-once"))

    assert seen == [user.id]
    assert repeated.id == user.id
    assert len(await events_of(session_factory, user.id)) == len(DEMO_EVENTS)


async def test_guest_account_starts_with_examples(session_factory) -> None:
    service = AuthService(session_factory, auth_settings(demo_seed_enabled=True))

    guest = await service.open_guest_session()
    other = await service.open_guest_session()

    first = await events_of(session_factory, guest.user_id)
    second = await events_of(session_factory, other.user_id)
    assert len(first) == len(DEMO_EVENTS)
    assert len(second) == len(DEMO_EVENTS)
    assert {event.id for event in first}.isdisjoint({event.id for event in second})


async def test_seeding_can_be_switched_off(session_factory) -> None:
    service = AuthService(session_factory, auth_settings(demo_seed_enabled=False))

    guest = await service.open_guest_session()

    assert await events_of(session_factory, guest.user_id) == []


async def test_first_bot_message_fills_the_account(session_factory, settings) -> None:
    assistant = AssistantService(
        session_factory,
        settings.model_copy(update={"demo_seed_enabled": True}),
        llm=SilentLLM(),
    )

    await assistant.handle_text(Platform.TELEGRAM, "42", "привет")

    async with session_factory() as session:
        user = await session.scalar(
            select(User).where(User.platform == Platform.TELEGRAM, User.external_id == "42")
        )
    assert user is not None
    assert len(await events_of(session_factory, user.id)) == len(DEMO_EVENTS)
