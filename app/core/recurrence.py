"""Recurrence utilities (RFC 5545 RRULE) and Russian natural language detection."""
from __future__ import annotations

import re
from datetime import datetime

from dateutil.rrule import rrulestr

_WEEKDAY_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(?:кажд(?:ый|ого)\s+понедельник|по\s+понедельникам|в\s+понедельники)\b", re.IGNORECASE), "FREQ=WEEKLY;BYDAY=MO", "каждый понедельник"),
    (re.compile(r"\b(?:кажд(?:ый|ого)\s+вторник|по\s+вторникам|во\s+вторники)\b", re.IGNORECASE), "FREQ=WEEKLY;BYDAY=TU", "каждый вторник"),
    (re.compile(r"\b(?:кажд(?:ую|ой)\s+среду|по\s+средам|в\s+среды)\b", re.IGNORECASE), "FREQ=WEEKLY;BYDAY=WE", "каждую среду"),
    (re.compile(r"\b(?:кажд(?:ый|ого)\s+четверг|по\s+четвергам|в\s+четверги)\b", re.IGNORECASE), "FREQ=WEEKLY;BYDAY=TH", "каждый четверг"),
    (re.compile(r"\b(?:кажд(?:ую|ой)\s+пятниц[уе]|по\s+пятницам|в\s+пятницы)\b", re.IGNORECASE), "FREQ=WEEKLY;BYDAY=FR", "каждую пятницу"),
    (re.compile(r"\b(?:кажд(?:ую|ой)\s+суббот[уе]|по\s+субботам|в\s+субботы)\b", re.IGNORECASE), "FREQ=WEEKLY;BYDAY=SA", "каждую субботу"),
    (re.compile(r"\b(?:кажд(?:ое|ого)\s+воскресень[ея]|по\s+воскресеньям|в\s+воскресенья)\b", re.IGNORECASE), "FREQ=WEEKLY;BYDAY=SU", "каждое воскресенье"),
]

_COMMON_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(?:по\s+будням|по\s+рабочим\s+дням|каждый\s+будний\s+день)\b", re.IGNORECASE), "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "по будням"),
    (re.compile(r"\b(?:по\s+выходным|каждые\s+выходные)\b", re.IGNORECASE), "FREQ=WEEKLY;BYDAY=SA,SU", "по выходным"),
    (re.compile(r"\b(?:каждый\s+день|ежедневно|раз\s+в\s+день)\b", re.IGNORECASE), "FREQ=DAILY", "каждый день"),
    (re.compile(r"\b(?:каждую\s+неделю|еженедельно|раз\s+в\s+неделю)\b", re.IGNORECASE), "FREQ=WEEKLY", "каждую неделю"),
    (re.compile(r"\b(?:каждый\s+месяц|ежемесячно|раз\s+в\s+месяц)\b", re.IGNORECASE), "FREQ=MONTHLY", "каждый месяц"),
]

_KNOWN_RULES_RU: dict[str, str] = {
    "FREQ=WEEKLY;BYDAY=MO": "каждый понедельник",
    "FREQ=WEEKLY;BYDAY=TU": "каждый вторник",
    "FREQ=WEEKLY;BYDAY=WE": "каждую среду",
    "FREQ=WEEKLY;BYDAY=TH": "каждый четверг",
    "FREQ=WEEKLY;BYDAY=FR": "каждую пятницу",
    "FREQ=WEEKLY;BYDAY=SA": "каждую субботу",
    "FREQ=WEEKLY;BYDAY=SU": "каждое воскресенье",
    "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR": "по будням",
    "FREQ=WEEKLY;BYDAY=SA,SU": "по выходным",
    "FREQ=DAILY": "каждый день",
    "FREQ=WEEKLY": "каждую неделю",
    "FREQ=MONTHLY": "каждый месяц",
}

_BYDAY_TO_WEEKDAY: dict[str, int] = {
    "MO": 0,
    "TU": 1,
    "WE": 2,
    "TH": 3,
    "FR": 4,
    "SA": 5,
    "SU": 6,
}


def detect_rrule(text: str | None) -> str | None:
    """Detects recurring event rules from Russian speech/text if present."""
    if not text:
        return None
    for pattern, rrule, _ in _WEEKDAY_PATTERNS:
        if pattern.search(text):
            return rrule
    for pattern, rrule, _ in _COMMON_PATTERNS:
        if pattern.search(text):
            return rrule
    return None


def format_rrule_ru(rrule: str | None) -> str | None:
    """Converts standard RFC 5545 RRULE into readable Russian text."""
    if not rrule:
        return None
    clean = rrule.strip().upper().replace("RRULE:", "")
    if clean in _KNOWN_RULES_RU:
        return _KNOWN_RULES_RU[clean]
    # Check parts:
    parts = dict(part.split("=", 1) for part in clean.split(";") if "=" in part)
    freq = parts.get("FREQ")
    byday = parts.get("BYDAY")
    if freq == "WEEKLY" and byday:
        days_map = {
            "MO": "пн",
            "TU": "вт",
            "WE": "ср",
            "TH": "чт",
            "FR": "пт",
            "SA": "сб",
            "SU": "вс",
        }
        human_days = ", ".join(days_map.get(d, d) for d in byday.split(","))
        return f"каждую неделю ({human_days})"
    if freq == "DAILY":
        return "ежедневно"
    if freq == "MONTHLY":
        return "ежемесячно"
    return clean


def next_recurrence(rrule_str: str, dtstart: datetime, after: datetime) -> datetime | None:
    """Calculates next occurrence of recurring rule strictly after `after` datetime."""
    try:
        clean = rrule_str.strip().replace("RRULE:", "")
        rule = rrulestr(clean, dtstart=dtstart)
        return rule.after(after)
    except Exception:
        return None


def align_starts_at_with_rrule(moment: datetime | None, rrule_str: str | None) -> datetime | None:
    """If rrule has BYDAY specified, ensures moment starts on one of those allowed weekdays."""
    if moment is None or not rrule_str:
        return moment

    clean = rrule_str.strip().upper().replace("RRULE:", "")
    parts = dict(part.split("=", 1) for part in clean.split(";") if "=" in part)
    byday = parts.get("BYDAY")
    if not byday:
        return moment

    target_days = {_BYDAY_TO_WEEKDAY[d] for d in byday.split(",") if d in _BYDAY_TO_WEEKDAY}
    if not target_days:
        return moment

    # If moment is already on one of the target days, nothing to adjust
    if moment.weekday() in target_days:
        return moment

    # Otherwise advance moment to the nearest upcoming target day preserving time and tz
    for delta in range(1, 8):
        from datetime import timedelta
        candidate = moment + timedelta(days=delta)
        if candidate.weekday() in target_days:
            return candidate

    return moment
