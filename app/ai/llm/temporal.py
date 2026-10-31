"""Спрашивает у модели, что сказано о времени, отдельным узким вызовом.

Чат-модель хорошо читает фразу и плохо считает даты в том же проходе, где пишет ответ.
Этот вызов возвращает только факты: названы ли дата и время, какой день недели и о какой
записи речь. Арифметику и правила решает вызывающий код.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol

from app.core.logger import get_logger

log = get_logger(__name__)

_WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
_WEEKDAYS_SHORT = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

_FACTS_SCHEMA = (
    '{"has_date": bool, "date": "YYYY-MM-DD" | null, "has_time": bool, '
    '"time": "HH:MM" | null, "weekday": "понедельник"|"вторник"|"среда"|"четверг"|'
    '"пятница"|"суббота"|"воскресенье" | null, "kind": "task"|"reminder"|"meeting"|null, '
    '"subject": string | null}'
)


class JsonModel(Protocol):
    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any): ...


@dataclass(frozen=True)
class TemporalFacts:
    has_date: bool = False
    date: date | None = None
    has_time: bool = False
    time: time | None = None
    weekday: str | None = None
    kind: str | None = None
    subject: str | None = None


def build_extraction_prompt(now: datetime) -> str:
    upcoming = ", ".join(
        f"{_WEEKDAYS_SHORT[(now + timedelta(days=offset)).weekday()]} "
        f"{(now + timedelta(days=offset)).strftime('%d.%m.%Y')}"
        for offset in range(0, 8)
    )
    return (
        "Ты извлекаешь из фразы пользователя только дату, время и предмет записи. "
        f"Сейчас {now.strftime('%d.%m.%Y %H:%M')}, {_WEEKDAYS[now.weekday()]}. "
        f"Ближайшие дни: {upcoming}. "
        "Ответь одним JSON-объектом без пояснений и без markdown: " + _FACTS_SCHEMA + ". "
        "has_time=true только если пользователь назвал часы или время суток; "
        "«завтра», «в пятницу» — это дата, а не время. "
        "date заполняй, когда дата названа или однозначно следует из дня недели. "
        "weekday заполняй, только если день недели назван словами. "
        "kind — что просит пользователь: задача, напоминание или встреча; "
        "«напомни» — reminder, «встреча» — meeting, остальное — task. "
        "subject — название записи, о которой идёт речь, без глаголов и без времени; "
        "null, если пользователь ничего не меняет и не ищет."
    )


def _json_object(raw: str) -> dict[str, Any] | None:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        value = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _parse_date(raw: Any) -> date | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_time(raw: Any) -> time | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.strptime(raw.strip(), "%H:%M").time()
    except ValueError:
        return None


def facts_from_payload(payload: dict[str, Any]) -> TemporalFacts:
    weekday = payload.get("weekday")
    weekday = weekday.strip().lower() if isinstance(weekday, str) else None
    if weekday not in _WEEKDAYS:
        weekday = None
    kind = payload.get("kind")
    kind = kind.strip().lower() if isinstance(kind, str) else None
    if kind not in ("task", "reminder", "meeting"):
        kind = None
    subject = payload.get("subject")
    subject = " ".join(subject.split()) if isinstance(subject, str) and subject.strip() else None
    moment_date = _parse_date(payload.get("date"))
    clock = _parse_time(payload.get("time"))
    return TemporalFacts(
        has_date=bool(payload.get("has_date")) or moment_date is not None,
        date=moment_date,
        has_time=bool(payload.get("has_time")) or clock is not None,
        time=clock,
        weekday=weekday,
        kind=kind,
        subject=subject,
    )


async def extract_temporal(llm: JsonModel, text: str, now: datetime) -> TemporalFacts | None:
    if not text.strip():
        return None
    messages = [
        {"role": "system", "content": build_extraction_prompt(now)},
        {"role": "user", "content": text},
    ]
    try:
        completion = await llm.chat(messages, temperature=0.0, max_tokens=150)
    except Exception as error:  # noqa: BLE001 - extraction is an optimisation, never a blocker
        log.warning("temporal extraction failed: %s", error)
        return None
    payload = _json_object(getattr(completion, "content", "") or "")
    if payload is None:
        log.info("temporal extraction returned no JSON")
        return None
    return facts_from_payload(payload)


def weekday_date(weekday: str | None, today: date) -> date | None:
    if weekday not in _WEEKDAYS:
        return None
    delta = (_WEEKDAYS.index(weekday) - today.weekday()) % 7
    return today + timedelta(days=delta)


def moment_from_facts(
    facts: TemporalFacts,
    moment: datetime | None,
    *,
    now: datetime,
) -> datetime | None:
    """Сводит факты о времени с тем, что предложила чат-модель."""
    day = facts.date or weekday_date(facts.weekday, now.date())
    clock = facts.time
    if day is None and clock is None:
        return moment
    if day is None:
        if moment is not None:
            day = moment.date()
        else:
            day = now.date() if clock is not None and clock > now.time() else now.date() + timedelta(days=1)
    if clock is None:
        clock = moment.time() if moment is not None else None
    if clock is None:
        return None
    return datetime.combine(day, clock, tzinfo=now.tzinfo)
