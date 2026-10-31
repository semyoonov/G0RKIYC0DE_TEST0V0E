"""Выгрузка в iCalendar (.ics) через библиотеку icalendar (RFC 5545).

Есть явное описание пояса Europe/Moscow (VTIMEZONE), правила повтора (RRULE)
и стандартные оповещения (VALARM).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Sequence
from zoneinfo import ZoneInfo

from icalendar import Alarm, Calendar, Event as ICalEvent, Timezone, TimezoneStandard, vRecur

from app.core.timeutils import ensure_aware, utcnow
from app.db.models.event import Event
from app.domain.enums import EVENT_TYPE_TITLES, EventStatus, EventType

PROD_ID = "-//GORKYCODE//Gorky Voice Assistant//RU"
CALENDAR_NAME = "Ассистент задач и встреч"
DEFAULT_TZ_NAME = "Europe/Moscow"
_DURATION_RE = re.compile(r"Длительность:\s*(\d+)\s*мин", re.IGNORECASE)


def build_moscow_vtimezone() -> Timezone:
    """Собирает VTIMEZONE для Europe/Moscow по RFC 5545."""
    tz = Timezone()
    tz.add("tzid", "Europe/Moscow")
    tz.add("x-lic-location", "Europe/Moscow")

    std = TimezoneStandard()
    std.add("tzname", "MSK")
    std.add("dtstart", datetime(1970, 1, 1, 0, 0, 0))
    std.add("tzoffsetfrom", timedelta(hours=3))
    std.add("tzoffsetto", timedelta(hours=3))

    tz.add_component(std)
    return tz


def _extract_duration_minutes(description: str | None, default_minutes: int) -> int:
    if not description:
        return default_minutes
    match = _DURATION_RE.search(description)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return default_minutes


def export_events_to_ics(
    events: Sequence[Event],
    timezone_name: str = DEFAULT_TZ_NAME,
) -> bytes:
    """Выгружает записи пользователя в байты iCalendar (.ics)."""
    tz = ZoneInfo(timezone_name)
    now_utc = utcnow()

    cal = Calendar()
    cal.add("prodid", PROD_ID)
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", CALENDAR_NAME)
    cal.add("x-wr-timezone", timezone_name)

    # Явный VTIMEZONE нужен для совместимости с Outlook, Apple, Google и Яндекс.Календарём
    if timezone_name == "Europe/Moscow":
        cal.add_component(build_moscow_vtimezone())

    for event in events:
        if event.status is EventStatus.CANCELLED:
            continue

        vevent = ICalEvent()
        vevent.add("uid", f"event-{event.id}@gorkycode")

        type_title = EVENT_TYPE_TITLES.get(event.type, "Запись")
        vevent.add("summary", f"{type_title}: {event.title}")

        if event.description:
            vevent.add("description", event.description)

        status_str = "COMPLETED" if event.status is EventStatus.DONE else "CONFIRMED"
        vevent.add("status", status_str)

        # Метки времени
        created_utc = ensure_aware(event.created_at).astimezone(timezone.utc) if event.created_at else now_utc
        updated_utc = ensure_aware(event.updated_at).astimezone(timezone.utc) if event.updated_at else created_utc
        vevent.add("dtstamp", now_utc)
        vevent.add("created", created_utc)
        vevent.add("last-modified", updated_utc)

        # Начало и конец
        moment = event.starts_at or event.remind_at
        if moment is not None:
            dtstart = ensure_aware(moment).astimezone(tz)
            default_duration = 30 if event.type is EventType.MEETING else 15
            duration_minutes = _extract_duration_minutes(event.description, default_duration)
            dtend = dtstart + timedelta(minutes=duration_minutes)
            vevent.add("dtstart", dtstart)
            vevent.add("dtend", dtend)
        else:
            # Задача без даты: выгружаем событием на весь день в дату создания
            c_date = created_utc.astimezone(tz).date()
            vevent.add("dtstart", c_date)
            vevent.add("dtend", c_date + timedelta(days=1))

        # Правило повтора (RRULE)
        if event.rrule:
            clean_rrule = event.rrule.strip().replace("RRULE:", "").strip()
            if clean_rrule:
                try:
                    vevent.add("rrule", vRecur.from_ical(clean_rrule))
                except Exception:
                    pass

        # Оповещение (VALARM)
        alarm = Alarm()
        alarm.add("action", "DISPLAY")
        alarm.add("description", f"Напоминание: {event.title}")
        if event.type is EventType.MEETING:
            # За 15 минут до встречи
            alarm.add("trigger", -timedelta(minutes=15))
        else:
            # В момент начала задачи или напоминания
            alarm.add("trigger", timedelta(0))
        vevent.add_component(alarm)

        cal.add_component(vevent)

    return cal.to_ical()
