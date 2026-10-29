from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from icalendar import Calendar

from app.core.recurrence import detect_rrule, format_rrule_ru, next_recurrence
from app.db.models.event import Event
from app.domain.enums import EventStatus, EventType
from app.services.calendar_export import export_events_to_ics


def test_detect_rrule() -> None:
    assert detect_rrule("поставь созвон каждый вторник в 10:00") == "FREQ=WEEKLY;BYDAY=TU"
    assert detect_rrule("напомни полить цветы по пятницам") == "FREQ=WEEKLY;BYDAY=FR"
    assert detect_rrule("планируй стендап по будням в 9:00") == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    assert detect_rrule("принимать витамины каждый день") == "FREQ=DAILY"
    assert detect_rrule("отчёт каждую неделю") == "FREQ=WEEKLY"
    assert detect_rrule("простая разовая встреча завтра") is None


def test_format_rrule_ru() -> None:
    assert format_rrule_ru("FREQ=WEEKLY;BYDAY=TU") == "каждый вторник"
    assert format_rrule_ru("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR") == "по будням"
    assert format_rrule_ru("FREQ=DAILY") == "каждый день"
    assert format_rrule_ru(None) is None


def test_next_recurrence() -> None:
    moscow = ZoneInfo("Europe/Moscow")
    dtstart = datetime(2025, 3, 4, 10, 0, tzinfo=moscow)  # Tuesday
    after = datetime(2025, 3, 5, 0, 0, tzinfo=moscow)
    nxt = next_recurrence("FREQ=WEEKLY;BYDAY=TU", dtstart, after)
    assert nxt is not None
    assert nxt.day == 11
    assert nxt.hour == 10


def test_export_events_to_ics() -> None:
    moscow = ZoneInfo("Europe/Moscow")
    now = datetime(2025, 3, 4, 10, 0, tzinfo=moscow)

    ev1 = Event(
        id=1,
        user_id=1,
        type=EventType.MEETING,
        title="Созвон с командой",
        description="Обсуждение проекта\nДлительность: 45 мин.",
        starts_at=now,
        rrule="FREQ=WEEKLY;BYDAY=TU",
        status=EventStatus.PENDING,
        created_at=now - timedelta(days=1),
        updated_at=now,
    )

    ev2 = Event(
        id=2,
        user_id=1,
        type=EventType.TASK,
        title="Купить кофе",
        description=None,
        starts_at=now + timedelta(days=1),
        rrule=None,
        status=EventStatus.DONE,
        created_at=now,
        updated_at=now,
    )

    ics_bytes = export_events_to_ics([ev1, ev2], timezone_name="Europe/Moscow")
    assert isinstance(ics_bytes, bytes)
    assert len(ics_bytes) > 0

    cal = Calendar.from_ical(ics_bytes)
    assert cal.get("prodid") == "-//GORKYCODE//Gorky Voice Assistant//RU"
    assert cal.get("x-wr-timezone") == "Europe/Moscow"

    # Verify VTIMEZONE
    timezones = [c for c in cal.subcomponents if c.name == "VTIMEZONE"]
    assert len(timezones) == 1
    assert timezones[0]["tzid"] == "Europe/Moscow"

    # Verify VEVENTs
    vevents = [c for c in cal.subcomponents if c.name == "VEVENT"]
    assert len(vevents) == 2

    # Check recurring meeting
    ev1_comp = next(v for v in vevents if "Созвон с командой" in str(v.get("summary")))
    assert ev1_comp.get("rrule") is not None
    assert ev1_comp.get("rrule")["FREQ"] == ["WEEKLY"]
    assert b"FREQ=WEEKLY" in ev1_comp.get("rrule").to_ical()
    assert ev1_comp.get("status") == "CONFIRMED"

    # Check VALARM in meeting
    alarms = [c for c in ev1_comp.subcomponents if c.name == "VALARM"]
    assert len(alarms) == 1
    assert alarms[0].get("trigger").dt == -timedelta(minutes=15)

    # Check completed task
    ev2_comp = next(v for v in vevents if "Купить кофе" in str(v.get("summary")))
    assert ev2_comp.get("status") == "COMPLETED"
