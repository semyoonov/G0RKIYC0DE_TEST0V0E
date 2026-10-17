from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.core.timeutils import ensure_aware, utcnow

_WEEKDAYS = {
    "понедельник": 0,
    "понедельника": 0,
    "вторник": 1,
    "вторника": 1,
    "среду": 2,
    "среда": 2,
    "среды": 2,
    "четверг": 3,
    "четверга": 3,
    "пятницу": 4,
    "пятница": 4,
    "пятницы": 4,
    "субботу": 5,
    "суббота": 5,
    "субботы": 5,
    "воскресенье": 6,
    "воскресенья": 6,
}
_WEEKDAY_RE = "|".join(sorted(_WEEKDAYS, key=len, reverse=True))

_MONTHS = {
    "января": 1,
    "январь": 1,
    "февраля": 2,
    "февраль": 2,
    "марта": 3,
    "март": 3,
    "апреля": 4,
    "апрель": 4,
    "мая": 5,
    "май": 5,
    "июня": 6,
    "июнь": 6,
    "июля": 7,
    "июль": 7,
    "августа": 8,
    "август": 8,
    "сентября": 9,
    "сентябрь": 9,
    "октября": 10,
    "октябрь": 10,
    "ноября": 11,
    "ноябрь": 11,
    "декабря": 12,
    "декабрь": 12,
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_COMPLETE_RE = re.compile(r"\b(выполн\w*|сделал\w*|готово|заверш\w*|отметь\w*)\b", re.IGNORECASE)
_DELETE_RE = re.compile(r"\b(удали\w*|убери|убрать)\b", re.IGNORECASE)
_LIST_RE = re.compile(
    r"(что у меня|что запланировано|какие задачи|какие встречи|есть ли у меня|что на сегодня"
    r"|что на завтра|что на недел|покажи|список)",
    re.IGNORECASE,
)
_SEARCH_RE = re.compile(r"\b(найди|найти|поищи|поискать|когда у меня|когда была|когда был)\b", re.IGNORECASE)
_MEETING_RE = re.compile(r"\bвстреч\w*\b", re.IGNORECASE)
_TASK_RE = re.compile(
    r"\b(напомни\w*|напоминание|задач\w*|купить|позвонить|отправить|подготовить|сделать|запиши)\b",
    re.IGNORECASE,
)
_REMINDER_RE = re.compile(r"\b(напомни\w*|напоминание)\b", re.IGNORECASE)

_TITLE_LEAD = re.compile(
    r"^(?:пожалуйста|мне|поставь|поставить|создай|создать|добавь|добавить|запланируй|запланировать"
    r"|напомни|напомнить|запиши|записать|нужно|надо|необходимо|у меня есть|у меня)\s+",
    re.IGNORECASE,
)
_TITLE_NOUN = re.compile(
    r"^(?:задачу|задача|задачи|напоминание|напоминания|встречу|встреча|встречи|событие)\s+",
    re.IGNORECASE,
)
_TITLE_PREP = re.compile(r"^(?:про|о|об)\s+", re.IGNORECASE)
_SEARCH_NOISE = re.compile(
    r"\b(найди|найти|поищи|поискать|покажи|пожалуйста|мне|у меня|когда|была|был|были|задачу|задача"
    r"|задачи|запись|записи|встречу|встреча|встречи|событие|события|про|о|об)\b",
    re.IGNORECASE,
)


@dataclass
class _When:
    date: date | None = None
    time: time | None = None


@dataclass
class LocalAction:
    tool: str
    arguments: dict[str, Any]


class LocalInterpreter:
    """Rule-based stand-in for the LLM: handles the required scenarios without GigaChat."""

    def __init__(self, tz: ZoneInfo) -> None:
        self._tz = tz

    def interpret(self, text: str, now: datetime | None = None) -> LocalAction | None:
        raw = " ".join(text.strip().split())
        if not raw:
            return None
        current = ensure_aware(now or utcnow()).astimezone(self._tz)

        if _COMPLETE_RE.search(raw):
            return self._with_id(raw, "complete_event")
        if _DELETE_RE.search(raw):
            return self._with_id(raw, "delete_event")
        if _LIST_RE.search(raw):
            return LocalAction("list_events", {"period": self._period(raw)})
        if _SEARCH_RE.search(raw):
            query = self._search_query(raw)
            return LocalAction("search_events", {"query": query}) if query else None
        if _MEETING_RE.search(raw):
            return self._create(raw, current, as_meeting=True)
        if _TASK_RE.search(raw):
            return self._create(raw, current, as_meeting=False)
        return None

    def _with_id(self, raw: str, tool: str) -> LocalAction | None:
        match = re.search(r"#?(\d{1,6})\b", raw)
        if match is None:
            return None
        return LocalAction(tool, {"event_id": int(match.group(1))})

    def _search_query(self, raw: str) -> str | None:
        cleaned = _SEARCH_NOISE.sub(" ", raw)
        cleaned = re.sub(r"[^\w\s\-]", " ", cleaned)
        cleaned = " ".join(cleaned.split())
        return cleaned or None

    @staticmethod
    def _period(raw: str) -> str:
        lowered = raw.lower()
        if "сегодня" in lowered:
            return "today"
        if "завтра" in lowered:
            return "tomorrow"
        if "недел" in lowered:
            return "week"
        return "week"

    def _create(self, raw: str, current: datetime, *, as_meeting: bool) -> LocalAction | None:
        when, remainder = self._extract_when(raw, current)
        title = self._title(remainder, as_meeting=as_meeting)
        if not title:
            return None

        arguments: dict[str, Any] = {"title": title}
        moment = self._compose_moment(when, current, as_meeting=as_meeting)
        if moment is not None:
            arguments["starts_at"] = moment.isoformat()
        if as_meeting:
            return LocalAction("create_meeting", arguments)
        if _REMINDER_RE.search(raw):
            arguments["is_reminder"] = True
            if moment is not None:
                arguments["remind_at"] = moment.isoformat()
        return LocalAction("create_task", arguments)

    def _compose_moment(self, when: _When, current: datetime, *, as_meeting: bool) -> datetime | None:
        if when.date is None and when.time is None:
            return None
        target_date = when.date or current.date()
        if when.time is None:
            if as_meeting:
                return None
            return datetime.combine(target_date, time(23, 59), tzinfo=self._tz)
        moment = datetime.combine(target_date, when.time, tzinfo=self._tz)
        if when.date is None and moment <= current:
            moment += timedelta(days=1)
        return moment

    def _extract_when(self, raw: str, current: datetime) -> tuple[_When, str]:
        text = raw
        when = _When()
        weekday_today = False

        relative = re.search(r"\bчерез\s+(\d+)\s*(час\w*|минут\w*|день|дня|дней)\b", text, re.IGNORECASE)
        if relative is not None:
            amount = int(relative.group(1))
            unit = relative.group(2).lower()
            if unit.startswith("час"):
                delta = timedelta(hours=amount)
            elif unit.startswith("мин"):
                delta = timedelta(minutes=amount)
            else:
                delta = timedelta(days=amount)
            moment = current + delta
            return _When(moment.date(), moment.replace(second=0, microsecond=0).time()), self._cut(text, relative)

        deadline = re.search(r"\b(до конца недели|к концу недели|до воскресенья)\b", text, re.IGNORECASE)
        if deadline is not None:
            days_ahead = 6 - current.weekday()
            when.date = (current + timedelta(days=days_ahead)).date()
            when.time = time(23, 59)
            text = self._cut(text, deadline)

        if when.date is None:
            for phrase, offset in (("послезавтра", 2), ("завтра", 1), ("сегодня", 0)):
                match = re.search(rf"\b{phrase}\b", text, re.IGNORECASE)
                if match is not None:
                    when.date = (current + timedelta(days=offset)).date()
                    text = self._cut(text, match)
                    break

        if when.date is None:
            match = re.search(rf"\b(?:в|во|на)\s+({_WEEKDAY_RE})\b", text, re.IGNORECASE)
            if match is None:
                match = re.search(rf"\b({_WEEKDAY_RE})\b", text, re.IGNORECASE)
            if match is not None:
                target = _WEEKDAYS[match.group(1).lower()]
                days_ahead = (target - current.weekday()) % 7
                weekday_today = days_ahead == 0
                when.date = (current + timedelta(days=days_ahead)).date()
                text = self._cut(text, match)

        if when.date is None:
            match = re.search(rf"\b(\d{{1,2}})\s+({_MONTH_RE})\b", text, re.IGNORECASE)
            if match is not None:
                day = int(match.group(1))
                month = _MONTHS[match.group(2).lower()]
                try:
                    when.date = date(current.year, month, day)
                except ValueError:
                    when.date = None
                if when.date is not None and when.date < current.date():
                    when.date = date(current.year + 1, month, day)
                text = self._cut(text, match)

        time_match = re.search(
            r"\b(?:в|во|к|на)\s+(\d{1,2})(?::(\d{2}))?\s*(утра|дня|вечера|ночи)?\b",
            text,
            re.IGNORECASE,
        )
        if time_match is None:
            time_match = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
        if time_match is not None:
            hour = self._adjust_hour(int(time_match.group(1)), (time_match.group(3) or "").lower())
            minute = int(time_match.group(2) or 0)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                when.time = time(hour, minute)
                text = self._cut(text, time_match)
            else:
                when.time = None

        if weekday_today and when.date is not None:
            if when.time is None or when.time <= current.time():
                when.date = when.date + timedelta(days=7)

        return when, text

    @staticmethod
    def _adjust_hour(hour: int, period: str) -> int:
        if period in ("дня", "вечера") and hour < 12:
            return hour + 12
        if period == "ночи" and hour >= 12:
            return hour - 12
        if period == "утра" and hour == 12:
            return 0
        return hour

    def _title(self, raw: str, *, as_meeting: bool) -> str | None:
        text = re.sub(r"[^\w\s\-ёЁ]", " ", raw)
        text = " ".join(text.split())
        for _ in range(4):
            stripped = _TITLE_LEAD.sub("", text)
            stripped = _TITLE_NOUN.sub("", stripped)
            if stripped == text:
                break
            text = stripped
        text = _TITLE_PREP.sub("", text).strip()
        if as_meeting and text.lower().startswith("с "):
            text = f"встреча {text}"
        if not text:
            return None
        return text[0].upper() + text[1:]

    @staticmethod
    def _cut(text: str, match: re.Match[str]) -> str:
        return f"{text[: match.start()]} {text[match.end() :]}"
