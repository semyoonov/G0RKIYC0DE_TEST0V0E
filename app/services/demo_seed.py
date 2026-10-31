from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.core.timeutils import utcnow
from app.db.models.user import User
from app.domain.enums import EventStatus, EventType, Platform
from app.domain.models import EventCreate
from app.repositories.event_repository import EventRepository

__all__ = ["DEMO_EVENTS", "DemoEvent", "seed_demo_events"]

log = get_logger(__name__)

_WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


@dataclass(frozen=True, slots=True)
class DemoEvent:
    """A sample record placed relative to the day the account is created."""

    type: EventType
    title: str
    description: str | None
    in_days: int
    hour: int | None = None
    minute: int = 0
    repeat_weekly: bool = False


DEMO_EVENTS: tuple[DemoEvent, ...] = (
    DemoEvent(
        EventType.MEETING,
        "Созвон по макету календаря",
        "Показать неделю, повторяющиеся встречи и экспорт в календарь",
        in_days=0,
        hour=15,
    ),
    DemoEvent(EventType.TASK, "Проверить отчёт за неделю", None, in_days=0, hour=18, minute=30),
    DemoEvent(
        EventType.REMINDER,
        "Записаться к врачу",
        "Талон на приём заканчивается",
        in_days=1,
        hour=9,
        minute=30,
    ),
    DemoEvent(
        EventType.MEETING,
        "Демо для заказчика",
        "Созвон в переговорной, ссылка в письме",
        in_days=2,
        hour=11,
    ),
    DemoEvent(EventType.TASK, "Собрать обратную связь по прототипу", None, in_days=3),
    DemoEvent(EventType.REMINDER, "Забрать документы", "МФЦ закрывается в 20:00", in_days=5, hour=12),
    DemoEvent(
        EventType.MEETING,
        "Планёрка команды",
        "Коротко: что сделано и что мешает",
        in_days=7,
        hour=10,
        repeat_weekly=True,
    ),
)


def _starts_at(now: datetime, event: DemoEvent) -> datetime | None:
    if event.hour is None:
        return None
    moment = datetime.combine(
        (now + timedelta(days=event.in_days)).date(),
        time(event.hour, event.minute),
        tzinfo=now.tzinfo,
    )
    while moment <= now:
        moment += timedelta(days=1)
    return moment


def _weekly_rule(moment: datetime) -> str:
    weekday = _WEEKDAYS[moment.weekday()]
    return f"FREQ=WEEKLY;BYDAY={weekday};BYHOUR={moment.hour};BYMINUTE={moment.minute}"


async def seed_demo_events(session: AsyncSession, user: User, timezone: str) -> int:
    """Fill a brand-new account with sample tasks so the free calendar is not empty.

    Records are placed ahead of the current time, so every reviewer sees upcoming
    plans rather than history. The rows are flushed, not committed: the caller
    decides when the account creation transaction ends.
    """
    now = utcnow().astimezone(ZoneInfo(timezone))
    repository = EventRepository(session)
    for event in DEMO_EVENTS:
        starts_at = _starts_at(now, event)
        await repository.create(
            user.id,
            EventCreate(
                type=event.type,
                title=event.title,
                description=event.description,
                starts_at=starts_at,
                remind_at=(
                    starts_at - timedelta(minutes=15)
                    if event.type is EventType.REMINDER and starts_at is not None
                    else None
                ),
                rrule=_weekly_rule(starts_at) if event.repeat_weekly and starts_at else None,
                status=EventStatus.PENDING,
                source=Platform.WEB,
            ),
            commit=False,
        )
    return len(DEMO_EVENTS)
