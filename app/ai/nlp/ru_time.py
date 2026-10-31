"""Deterministic Russian date and time extraction.

The language model is not reliable at weekday arithmetic and tends to invent a
time when the user gave none. This module reads the user's own words, so tool
calls can be corrected and clarifying questions can be decided in code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

_JO = str.maketrans({"ё": "е", "Ё": "Е"})

_WEEKDAY_STEMS: dict[str, int] = {
    "понедельник": 0,
    "вторник": 1,
    "среду": 2,
    "среда": 2,
    "среды": 2,
    "среде": 2,
    "четверг": 3,
    "пятницу": 4,
    "пятница": 4,
    "пятницы": 4,
    "пятнице": 4,
    "субботу": 5,
    "суббота": 5,
    "субботы": 5,
    "субботе": 5,
    "воскресенье": 6,
    "воскресенья": 6,
    "воскресенью": 6,
}
_WEEKDAY_RE = re.compile(
    r"(?<![а-я])(?P<word>" + "|".join(sorted(_WEEKDAY_STEMS, key=len, reverse=True)) + r")(?![а-я])"
)

_RELATIVE_DAYS = {
    "сегодня": 0,
    "завтра": 1,
    "послезавтра": 2,
    "вчера": -1,
    "позавчера": -2,
}
_RELATIVE_DAY_RE = re.compile(
    r"(?<![а-я])(?P<word>" + "|".join(sorted(_RELATIVE_DAYS, key=len, reverse=True)) + r")(?![а-я])"
)

_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
_MONTH_DATE_RE = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})\s+(?P<month>" + "|".join(_MONTHS) + r")(?:\s+(?P<year>\d{4}))?"
)
_DOTTED_DATE_RE = re.compile(r"(?<!\d)(?P<day>\d{1,2})[./](?P<month>\d{1,2})(?:[./](?P<year>\d{2,4}))?(?!\d)")

_NUMBER_WORDS = {
    "один": 1,
    "одну": 1,
    "одного": 1,
    "два": 2,
    "две": 2,
    "двух": 2,
    "три": 3,
    "трех": 3,
    "четыре": 4,
    "четырех": 4,
    "пять": 5,
    "пяти": 5,
    "шесть": 6,
    "шести": 6,
    "семь": 7,
    "семи": 7,
    "восемь": 8,
    "восьми": 8,
    "девять": 9,
    "девяти": 9,
    "десять": 10,
    "десяти": 10,
    "одиннадцать": 11,
    "двенадцать": 12,
}
_NUMBER_RE = r"(?P<num>\d{1,2}|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"
_IN_DURATION_RE = re.compile(
    rf"(?<![а-я])через\s+{_NUMBER_RE}?\s*(?P<unit>минут[уы]?|час(?:а|ов)?|день|дня|дней|недел[юи]|месяц(?:а|ев)?)"
)
_HALF_HOUR_RE = re.compile(r"(?<![а-я])через\s+полчаса")

_SUFFIX_RE = r"(?P<suffix>утра|утром|дня|днем|вечера|вечером|ночи|ночью)"
_HHMM_RE = re.compile(r"(?<!\d)(?P<hour>\d{1,2}):(?P<minute>\d{2})(?!\d)")
_DOT_TIME_RE = re.compile(
    r"(?<![а-я])(?:в|к|около|после|до)\s+(?P<hour>\d{1,2})[.](?P<minute>\d{2})(?!\d)"
)
_AT_HOUR_RE = re.compile(
    rf"(?<![а-я])(?:в|к|около|после|до)\s+(?P<hour>\d{{1,2}})(?!\d)(?:\s*час(?:а|ов)?)?\s*{_SUFFIX_RE}?"
)
_BARE_HOUR_SUFFIX_RE = re.compile(rf"(?<!\d)(?P<hour>\d{{1,2}})\s*{_SUFFIX_RE}")
_WORD_HOUR_RE = re.compile(
    rf"(?<![а-я])(?:в|к)\s+(?:час|(?P<word>{'|'.join(_NUMBER_WORDS)}))\s*(?:час(?:а|ов)?)?\s*{_SUFFIX_RE}?"
)
_SPECIAL_TIMES = (
    (re.compile(r"(?<![а-я])в\s+полдень(?![а-я])"), time(12, 0)),
    (re.compile(r"(?<![а-я])в\s+полночь(?![а-я])"), time(0, 0)),
    (re.compile(r"(?<![а-я])в\s+(обед|обеденное время)(?![а-я])"), time(13, 0)),
)
_NEXT_WEEK_RE = re.compile(r"(?<![а-я])на\s+следующей\s+неделе(?![а-я])")
_WEEK_END_RE = re.compile(r"(?<![а-я])(?:до|к)\s+конца\s+(?P<unit>недели|месяца)(?![а-я])")


@dataclass(frozen=True)
class TemporalHint:
    """What the user said about time, resolved against one moment."""

    date: date | None = None
    time: time | None = None
    has_date: bool = False
    explicit_date: bool = False
    has_time: bool = False
    matched: str = ""

    def applies(self) -> bool:
        return self.has_date or self.has_time


def normalize(text: str) -> str:
    return (text or "").translate(_JO).lower().replace("\u00a0", " ")


def _number(raw: str | None) -> int | None:
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    return _NUMBER_WORDS.get(raw)


def _apply_suffix(hour: int, suffix: str | None) -> int | None:
    if not 0 <= hour <= 23:
        return None
    if suffix is None:
        return hour
    if suffix in ("утра", "утром"):
        return 0 if hour == 12 else hour
    if suffix in ("дня", "днем"):
        return hour if hour == 12 else (hour + 12 if hour < 12 else hour)
    if suffix in ("вечера", "вечером"):
        return hour + 12 if hour < 12 else hour
    if hour == 12:
        return 0
    if hour <= 5:
        return hour
    return hour + 12


def _time_of(hour: int, minute: int, suffix: str | None) -> time | None:
    adjusted = _apply_suffix(hour, suffix)
    if adjusted is None or minute > 59:
        return None
    return time(adjusted, minute)


def _next_weekday(today: date, target: int, *, force_next: bool) -> date:
    delta = (target - today.weekday()) % 7
    if force_next and delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def _spans_overlap(span: tuple[int, int], others: list[tuple[int, int]]) -> bool:
    return any(span[0] < other[1] and other[0] < span[1] for other in others)


def _first_match(pattern: re.Pattern[str], text: str, excluded: list[tuple[int, int]]):
    for match in pattern.finditer(text):
        if not _spans_overlap(match.span(), excluded):
            return match
    return None


def _extract_time(text: str, now: datetime, excluded: list[tuple[int, int]]) -> tuple[time | None, list[tuple[int, int]]]:
    """Return the first explicit clock time and the spans already consumed."""
    consumed: list[tuple[int, int]] = []
    found: time | None = None

    for pattern, value in _SPECIAL_TIMES:
        match = _first_match(pattern, text, excluded)
        if match:
            return value, [match.span()]

    match = _first_match(_HHMM_RE, text, excluded)
    if match:
        value = _time_of(int(match["hour"]), int(match["minute"]), None)
        if value is not None:
            found, consumed = value, [match.span()]

    if found is None:
        for pattern in (_AT_HOUR_RE, _BARE_HOUR_SUFFIX_RE):
            match = _first_match(pattern, text, excluded)
            if not match:
                continue
            value = _time_of(int(match["hour"]), 0, match.groupdict().get("suffix"))
            if value is not None:
                found, consumed = value, [match.span()]
                break

    if found is None:
        match = _first_match(_WORD_HOUR_RE, text, excluded)
        if match:
            hour = 1 if match["word"] is None else _NUMBER_WORDS.get(match["word"])
            value = _time_of(hour or 0, 0, match.groupdict().get("suffix"))
            if value is not None:
                found, consumed = value, [match.span()]

    if found is None:
        match = _first_match(_HALF_HOUR_RE, text, excluded)
        if match:
            moment = now + timedelta(minutes=30)
            found, consumed = moment.time().replace(second=0, microsecond=0), [match.span()]
        else:
            match = _first_match(_IN_DURATION_RE, text, excluded)
            if match and match.group("unit").startswith(("час", "минут")):
                amount = _number(match.group("num")) or 1
                delta = timedelta(hours=amount) if match.group("unit").startswith("час") else timedelta(minutes=amount)
                moment = now + delta
                found, consumed = moment.time().replace(second=0, microsecond=0), [match.span()]
    return found, consumed


def _extract_date(text: str, now: datetime) -> tuple[date | None, list[tuple[int, int]], str]:
    """Return the first date the user named, its span, and the matched text."""
    today = now.date()

    for pattern, month_names in ((_MONTH_DATE_RE, True), (_DOTTED_DATE_RE, False)):
        match = pattern.search(text)
        if not match:
            continue
        day = int(match["day"])
        month = _MONTHS[match["month"]] if month_names else int(match["month"])
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            continue
        year_raw = match.groupdict().get("year")
        year = today.year
        if year_raw:
            year = int(year_raw)
            if year < 100:
                year += 2000
        try:
            value = date(year, month, day)
        except ValueError:
            continue
        if not year_raw and value < today:
            try:
                value = date(year + 1, month, day)
            except ValueError:
                continue
        return value, [match.span()], match.group(0)

    match = _RELATIVE_DAY_RE.search(text)
    if match:
        return today + timedelta(days=_RELATIVE_DAYS[match["word"]]), [match.span()], match.group(0)

    match = _HALF_HOUR_RE.search(text)
    if match:
        return (now + timedelta(minutes=30)).date(), [], match.group(0)

    match = _IN_DURATION_RE.search(text)
    if match:
        amount = _number(match.group("num")) or 1
        unit = match.group("unit")
        if unit.startswith(("час", "минут")):
            delta = timedelta(hours=amount) if unit.startswith("час") else timedelta(minutes=amount)
            return (now + delta).date(), [], match.group(0)
        if unit.startswith("д"):
            return today + timedelta(days=amount), [match.span()], match.group(0)
        if unit.startswith("недел"):
            return today + timedelta(weeks=amount), [match.span()], match.group(0)
        if unit.startswith("месяц"):
            return today + timedelta(days=30 * amount), [match.span()], match.group(0)

    match = _WEEK_END_RE.search(text)
    if match:
        if match["unit"] == "недели":
            return today + timedelta(days=6 - today.weekday()), [match.span()], match.group(0)
        last_day = date(today.year + (today.month == 12), today.month % 12 + 1, 1) - timedelta(days=1)
        return last_day, [match.span()], match.group(0)

    match = _NEXT_WEEK_RE.search(text)
    if match:
        return today + timedelta(days=7 - today.weekday()), [match.span()], match.group(0)

    match = _WEEKDAY_RE.search(text)
    if match:
        before = text[max(0, match.start() - 14) : match.start()]
        force_next = "следующ" in before
        return _next_weekday(today, _WEEKDAY_STEMS[match["word"]], force_next=force_next), [match.span()], match.group(0)

    return None, [], ""


def parse_temporal(text: str, now: datetime, tz: ZoneInfo | None = None) -> TemporalHint:
    """Resolve the first date and the first clock time mentioned in `text`."""
    if tz is not None and now.tzinfo is not None:
        now = now.astimezone(tz)
    normalized = normalize(text)
    moment = now.replace(tzinfo=None) if now.tzinfo else now

    day, date_spans, date_source = _extract_date(normalized, moment)
    clock, time_spans = _extract_time(normalized, moment, date_spans)

    explicit_date = day is not None
    if clock is not None and day is None:
        day = moment.date() if clock > moment.time() else moment.date() + timedelta(days=1)
        date_source = ""

    if clock is None and day is not None:
        return TemporalHint(date=day, has_date=True, explicit_date=True, matched=date_source)
    if clock is not None:
        return TemporalHint(
            date=day,
            time=clock,
            has_date=day is not None,
            explicit_date=explicit_date,
            has_time=True,
            matched=(date_source + " " + normalized[time_spans[0][0] : time_spans[0][1]]).strip(),
        )
    return TemporalHint()


_TIME_HINT_RE = re.compile(
    r"\d{1,2}\s*[:.]\s*\d{2}"
    r"|(?<![а-я])час(?![а-я])"
    r"|(?<![а-я])(?:утра|утром|дня|днем|вечера|вечером|ночи|ночью|полдень|полночь|обед)(?![а-я])"
)


def looks_like_time(text: str) -> bool:
    """True when the text names a clock time, even one the parser did not resolve."""
    return bool(_TIME_HINT_RE.search(normalize(text)))


def apply_hint(moment: datetime | None, hint: TemporalHint, *, fallback_time: time | None = None) -> datetime | None:
    """Overlay the user's date and time on whatever the model proposed.

    A date is replaced only when the user actually named one, so a bare clock time
    keeps the day the model took from the previous turn.
    """
    if not hint.applies():
        return moment
    if moment is None:
        day = hint.date
        clock = hint.time or fallback_time
        if day is None or clock is None:
            return None
        return datetime.combine(day, clock)
    day = hint.date if hint.explicit_date else moment.date()
    clock = hint.time if hint.has_time else moment.time()
    return datetime.combine(day, clock).replace(tzinfo=moment.tzinfo)
