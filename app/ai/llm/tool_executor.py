import json
from collections.abc import Awaitable, Callable
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm.prompts import format_event_line, format_event_list
from app.ai.nlp.ru_time import TemporalHint, apply_hint, looks_like_time, parse_temporal
from app.core.config import Settings
from app.core.exceptions import AssistantError
from app.core.logger import get_logger
from app.core.timeutils import format_datetime, from_db, period_bounds
from app.db.models.event import Event
from app.db.models.user import User
from app.domain.enums import EventType, Period
from app.domain.models import EventCreate, EventRead, EventUpdate
from app.repositories.event_repository import EventRepository
from app.services.cache.redis_service import CacheService

log = get_logger(__name__)

ERROR_PREFIX = "ОШИБКА:"
_REMINDER_WORD = re.compile(r"напомн|напомин", re.I)
_CHANGE_VERB = re.compile(
    r"^\s*(?:пожалуйста[,\s]+)?(?:перенеси|перенести|передвинь|переставь|сдвинь|измени|изменить|"
    r"поменяй|обнови|переименуй|отметь|удали|убери)\s+",
    re.I,
)
_TIME_TAIL = re.compile(
    r"\s+(?:на|в|к|до)\s+\d{1,2}(?::\d{2})?|\s+(?:на\s+)?(?:сегодня|завтра|послезавтра|"
    r"понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)\b.*$",
    re.I,
)
# A day holds a handful of records; a month or "all" must not render a wall of cards.
LIST_LIMIT = 25
_ISO_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y")
_PERIOD_TITLES = {
    Period.TODAY: "сегодня",
    Period.TOMORROW: "завтра",
    Period.WEEK: "эту неделю",
    Period.ALL: "весь период",
    Period.CUSTOM: "указанный период",
}


def parse_datetime(value: Any, tz: ZoneInfo) -> datetime | None:
    if value in (None, "", "null", "None"):
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            moment = None
            for pattern in _ISO_FORMATS:
                try:
                    moment = datetime.strptime(text, pattern)
                    break
                except ValueError:
                    continue
            if moment is None:
                return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    return moment


def to_read(event: Event) -> EventRead:
    return EventRead.model_validate(event)


@dataclass
class ToolResult:
    name: str
    content: str
    events: list[EventRead] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.content.startswith(ERROR_PREFIX)


class ToolExecutor:
    """Executes GigaChat function calls against the repositories of one user."""

    def __init__(
        self,
        session: AsyncSession,
        user: User,
        settings: Settings,
        cache: CacheService | None = None,
        utterance: str = "",
    ) -> None:
        self._session = session
        self._user = user
        self._settings = settings
        self._cache = cache
        self._events = EventRepository(session)
        self._utterance = utterance or ""
        self._hint = parse_temporal(self._utterance, datetime.now(settings.tz), settings.tz)

    @property
    def tz(self) -> ZoneInfo:
        return self._settings.tz

    def _user_named_time(self) -> bool:
        """True when the user's own words contain a clock time.

        A time the model made up must never silence a clarifying question.
        """
        if not self._utterance:
            return True
        return self._hint.has_time or looks_like_time(self._utterance)

    def _utterance_query(self) -> str:
        """The record name, taken from the user's words when the model supplied none."""
        text = _CHANGE_VERB.sub("", self._utterance.strip())
        text = _TIME_TAIL.sub("", text)
        return " ".join(text.split()).strip(" .,!?;:")

    def _resolve(self, moment: datetime | None, *, date_only: time | None = None) -> datetime | None:
        """Overlay the user's date and time on the moment the model proposed."""
        hint: TemporalHint = self._hint
        if not hint.applies():
            return moment
        if moment is None:
            if hint.date is None or (hint.time is None and date_only is None):
                return None
            return datetime.combine(hint.date, hint.time or date_only, tzinfo=self.tz)
        return apply_hint(moment, hint)

    async def execute(self, name: str, arguments: dict[str, Any] | str) -> ToolResult:
        handler = self._handlers().get(name)
        if handler is None:
            return self._error(name, "неизвестное действие")
        parsed = self._parse_arguments(arguments)
        if parsed is None:
            return self._error(name, "не удалось разобрать аргументы вызова, переформулируйте запрос")
        try:
            return await handler(parsed)
        except AssistantError as error:
            log.warning("tool %s failed: %s", name, error)
            return self._error(name, str(error))
        except Exception:
            log.exception("tool %s crashed", name)
            return self._error(name, "не получилось выполнить действие, попробуйте ещё раз")

    def _handlers(self) -> dict[str, Callable[[dict[str, Any]], Awaitable[ToolResult]]]:
        return {
            "create_task": self._create_task,
            "create_meeting": self._create_meeting,
            "list_events": self._list_events,
            "search_events": self._search_events,
            "update_event": self._update_event,
            "complete_event": self._complete_event,
            "delete_event": self._delete_event,
        }

    _GENERIC_REMINDER_TITLES = frozenset({
        "напоминание",
        "напоминалка",
        "напомнить",
        "напомни",
        "напоминания",
        "напоминанием",
        "reminder",
        "remind",
        "новое напоминание",
        "без названия",
    })

    _GENERIC_TASK_TITLES = frozenset({
        "задача",
        "задачу",
        "задачи",
        "дело",
        "дела",
        "заметка",
        "заметку",
        "запись",
        "task",
        "новая задача",
        "новое дело",
        "без названия",
    })

    def _is_empty_or_generic_task_title(self, title: str | None, *, is_reminder: bool = False) -> bool:
        if not title:
            return True
        cleaned = title.strip(" .!?:;«»\"'").lower()
        if is_reminder:
            if cleaned in self._GENERIC_REMINDER_TITLES:
                return True
            for prefix in (
                "напоминание на ", "напоминание в ", "напоминание к ", "напоминание о ",
                "напомнить в ", "напомнить на ", "напомнить о ",
                "напомни в ", "напомни на ", "напомни о ",
            ):
                if cleaned.startswith(prefix):
                    return True
        else:
            if cleaned in self._GENERIC_TASK_TITLES:
                return True
            for prefix in ("задача на ", "задача в ", "задача к ", "дело на ", "сделать задачу"):
                if cleaned.startswith(prefix):
                    return True
        return False

    async def _create_task(self, arguments: dict[str, Any]) -> ToolResult:
        title = self._text(arguments.get("title"))
        is_reminder = bool(arguments.get("is_reminder"))
        if self._utterance and not _REMINDER_WORD.search(self._utterance):
            # «В пятницу нужно отправить отчет» — задача, даже если модель назвала её напоминанием.
            is_reminder = False
        if self._is_empty_or_generic_task_title(title, is_reminder=is_reminder):
            if is_reminder:
                return self._error("create_task", "как назвать напоминание? Уточни, о чём напомнить.")
            return self._error("create_task", "как назвать задачу? Уточни, что именно нужно сделать.")
        model_starts = parse_datetime(arguments.get("starts_at"), self.tz)
        if self._hint.explicit_date and not self._hint.has_time:
            # The user named a day only; a clock time the model added is not evidence.
            model_starts = None
        starts_at = self._resolve(model_starts, date_only=time(23, 59))
        remind_at = self._resolve(parse_datetime(arguments.get("remind_at"), self.tz))
        event_type = EventType.REMINDER if is_reminder else EventType.TASK
        if is_reminder:
            if not self._user_named_time():
                return self._error("create_task", "на какой день и время поставить напоминание?")
            if remind_at is None:
                remind_at = starts_at
            if remind_at is None:
                return self._error("create_task", "на какой день и время поставить напоминание?")
        if starts_at is None and remind_at is not None:
            starts_at = remind_at

        rrule = self._text(arguments.get("rrule"))
        if not rrule:
            from app.core.recurrence import detect_rrule
            rrule = detect_rrule(title) or detect_rrule(arguments.get("description"))

        if rrule:
            from app.core.recurrence import align_starts_at_with_rrule
            if starts_at is not None:
                starts_at = align_starts_at_with_rrule(starts_at, rrule)
            if remind_at is not None:
                remind_at = align_starts_at_with_rrule(remind_at, rrule)

        event = await self._events.create(
            self._user.id,
            EventCreate(
                type=event_type,
                title=title,
                description=self._text(arguments.get("description")),
                starts_at=starts_at,
                remind_at=remind_at,
                rrule=rrule,
                source=self._user.platform,
            ),
        )
        await self._invalidate_cache()

        verbs = {
            EventType.TASK: "Создал задачу",
            EventType.REMINDER: "Создал напоминание",
        }
        content = f"{verbs[event_type]} «{title}»"
        if starts_at is not None:
            if self._hint.has_date and not self._hint.has_time:
                content += f" — {starts_at.astimezone(self.tz):%d.%m.%Y} (время не указано)"
            else:
                content += f" — {format_datetime(starts_at, self.tz)}"
        content += "."
        if remind_at is not None and remind_at != starts_at:
            content += f" Напомню {format_datetime(remind_at, self.tz)}."
        if rrule:
            from app.core.recurrence import format_rrule_ru
            rrule_desc = format_rrule_ru(rrule)
            if rrule_desc:
                content += f" Повтор: {rrule_desc}."
        return ToolResult("create_task", content, [to_read(event)])

    _GENERIC_MEETING_TITLES = frozenset({
        "встреча",
        "встречу",
        "встречи",
        "meeting",
        "без названия",
        "новая встреча",
    })

    def _is_empty_or_generic_meeting_title(self, title: str | None) -> bool:
        if not title:
            return True
        cleaned = title.strip(" .!?:;«»\"'").lower()
        if cleaned in self._GENERIC_MEETING_TITLES:
            return True
        if cleaned.startswith("встреча на ") or cleaned.startswith("встреча в ") or cleaned.startswith("встреча к "):
            return True
        return False

    async def _create_meeting(self, arguments: dict[str, Any]) -> ToolResult:
        title = self._text(arguments.get("title"))
        if self._is_empty_or_generic_meeting_title(title):
            return self._error("create_meeting", "как назвать встречу?")
        starts_at = self._resolve(parse_datetime(arguments.get("starts_at"), self.tz))
        if not self._user_named_time():
            return self._error("create_meeting", "на какое время поставить встречу?")
        if starts_at is None:
            return self._error("create_meeting", "на какое время поставить встречу?")

        duration = self._int(arguments.get("duration_minutes"), self._settings.default_event_duration_minutes)
        description = self._text(arguments.get("description"))
        if duration != self._settings.default_event_duration_minutes:
            duration_note = f"Длительность: {duration} мин."
            description = f"{description}\n{duration_note}" if description else duration_note

        rrule = self._text(arguments.get("rrule"))
        if not rrule:
            from app.core.recurrence import detect_rrule
            rrule = detect_rrule(title) or detect_rrule(arguments.get("description"))

        if rrule and starts_at is not None:
            from app.core.recurrence import align_starts_at_with_rrule
            starts_at = align_starts_at_with_rrule(starts_at, rrule)

        conflict = await self._find_conflict(starts_at, duration)
        event = await self._events.create(
            self._user.id,
            EventCreate(
                type=EventType.MEETING,
                title=title,
                description=description,
                starts_at=starts_at,
                rrule=rrule,
                source=self._user.platform,
            ),
        )
        await self._invalidate_cache()

        content = f"Создал встречу: «{title}» — {format_datetime(starts_at, self.tz)}."
        if conflict is not None:
            content += f" В это время уже стоит «{conflict.title}»."
        if rrule:
            from app.core.recurrence import format_rrule_ru
            rrule_desc = format_rrule_ru(rrule)
            if rrule_desc:
                content += f" Повтор: {rrule_desc}."
        return ToolResult("create_meeting", content, [to_read(event)])

    async def _list_events(self, arguments: dict[str, Any]) -> ToolResult:
        period = self._period(arguments.get("period"))
        types = self._types(arguments.get("types"))
        if period is Period.CUSTOM:
            start = parse_datetime(arguments.get("date_from"), self.tz)
            end = parse_datetime(arguments.get("date_to"), self.tz)
            if start is None or end is None:
                return self._error("list_events", "за какой период показать записи?")
        else:
            start, end = period_bounds(period, self.tz)

        cache_key = self._cache_key(period, start, end, types)
        if self._cache is not None and cache_key is not None:
            cached = await self._cache.get_json(cache_key)
            if cached is not None:
                events = [EventRead.model_validate(item) for item in cached]
                return ToolResult("list_events", self._period_content(events, period), events[:LIST_LIMIT])

        events = await self._events.list_for_period(
            self._user.id,
            start,
            end,
            types=types,
            include_undated=period is Period.ALL,
        )
        read_events = [to_read(event) for event in events]
        if self._cache is not None and cache_key is not None:
            await self._cache.set_json(cache_key, [event.model_dump(mode="json") for event in read_events])
        return ToolResult("list_events", self._period_content(read_events, period), read_events[:LIST_LIMIT])

    async def _search_events(self, arguments: dict[str, Any]) -> ToolResult:
        query = self._text(arguments.get("query"))
        if not query:
            return self._error("search_events", "по каким словам искать?")
        limit = min(max(self._int(arguments.get("limit"), 5), 1), 20)
        events = await self._events.search(self._user.id, query, limit=limit)
        if not events:
            return ToolResult("search_events", f"Ничего не нашёл по запросу «{query}».")
        content = f"Нашёл {len(events)}:\n{format_event_list([to_read(event) for event in events], self.tz)}"
        return ToolResult("search_events", content, [to_read(event) for event in events])

    async def _update_event(self, arguments: dict[str, Any]) -> ToolResult:
        event_id = self._int(arguments.get("event_id"), 0)
        event = await self._events.get_for_user(self._user.id, event_id) if event_id else None
        if event is None:
            query = self._text(arguments.get("query")) or self._text(arguments.get("target_title"))
            if not query and self._utterance:
                query = self._utterance_query() or None
            if query:
                candidates = await self._events.search(self._user.id, query, limit=3)
                if candidates:
                    event = candidates[0]
                else:
                    return self._error("update_event", f"запись по запросу «{query}» не найдена")
            elif event_id:
                return self._error("update_event", f"запись {event_id} не найдена")
            else:
                return self._error("update_event", "какую запись изменить?")

        payload: dict[str, Any] = {}
        if self._text(arguments.get("title")):
            payload["title"] = self._text(arguments.get("title"))
        if "description" in arguments:
            payload["description"] = self._text(arguments.get("description"))
        if "rrule" in arguments:
            payload["rrule"] = self._text(arguments.get("rrule"))
        for field_name in ("starts_at", "remind_at"):
            if field_name in arguments:
                payload[field_name] = self._resolve(parse_datetime(arguments.get(field_name), self.tz))
        if self._hint.applies() and "starts_at" in arguments:
            payload["starts_at"] = self._resolve(payload.get("starts_at") or event.starts_at)
        elif "starts_at" not in arguments and (self._hint.has_time or self._hint.explicit_date):
            payload["starts_at"] = self._resolve(event.starts_at)

        active_rrule = payload.get("rrule") or event.rrule
        if active_rrule:
            from app.core.recurrence import align_starts_at_with_rrule
            if payload.get("starts_at"):
                payload["starts_at"] = align_starts_at_with_rrule(payload["starts_at"], active_rrule)
            if payload.get("remind_at"):
                payload["remind_at"] = align_starts_at_with_rrule(payload["remind_at"], active_rrule)

        if not payload:
            return self._error("update_event", "что именно изменить в записи?")

        updated = await self._events.update(event, EventUpdate(**payload))
        await self._invalidate_cache()
        return ToolResult(
            "update_event",
            f"Изменил: {format_event_line(to_read(updated), self.tz, with_id=False)}.",
            [to_read(updated)],
        )

    async def _complete_event(self, arguments: dict[str, Any]) -> ToolResult:
        event_id = self._int(arguments.get("event_id"), 0)
        event = await self._events.get_for_user(self._user.id, event_id) if event_id else None
        if event is None:
            query = self._text(arguments.get("query")) or self._text(arguments.get("title"))
            if query:
                candidates = await self._events.search(self._user.id, query, limit=3)
                if candidates:
                    event = candidates[0]
                else:
                    return self._error("complete_event", f"запись по запросу «{query}» не найдена")
            elif event_id:
                return self._error("complete_event", f"запись {event_id} не найдена")
            else:
                return self._error("complete_event", "какую запись отметить?")
        done = arguments.get("done", True)
        updated = await self._events.mark_done(event, done=bool(done))
        await self._invalidate_cache()
        verb = "Отметил как выполнено" if done else "Вернул в работу"
        return ToolResult(
            "complete_event",
            f"{verb}: {format_event_line(to_read(updated), self.tz, with_id=False)}.",
            [to_read(updated)],
        )

    async def _delete_event(self, arguments: dict[str, Any]) -> ToolResult:
        event_id = self._int(arguments.get("event_id"), 0)
        event = await self._events.get_for_user(self._user.id, event_id) if event_id else None
        if event is None:
            query = self._text(arguments.get("query")) or self._text(arguments.get("title"))
            if query:
                candidates = await self._events.search(self._user.id, query, limit=3)
                if candidates:
                    event = candidates[0]
                else:
                    return self._error("delete_event", f"запись по запросу «{query}» не найдена")
            elif event_id:
                return self._error("delete_event", f"запись {event_id} не найдена")
            else:
                return self._error("delete_event", "какую запись удалить?")
        line = format_event_line(to_read(event), self.tz, with_id=False)
        await self._events.delete(event)
        await self._invalidate_cache()
        return ToolResult("delete_event", f"Удалил: {line}.")

    async def _find_conflict(self, starts_at: datetime, duration_minutes: int) -> Event | None:
        window = timedelta(minutes=max(duration_minutes, 1))
        candidates = await self._events.list_for_period(
            self._user.id,
            starts_at - window,
            starts_at + window,
            types=[EventType.MEETING],
            include_done=False,
        )
        for candidate in candidates:
            other = from_db(candidate.starts_at)
            if other is not None and abs((other - starts_at).total_seconds()) < max(duration_minutes, 1) * 60:
                return candidate
        return None

    def _period_content(self, events: list[EventRead], period: Period) -> str:
        label = _PERIOD_TITLES[period]
        if not events:
            return f"На {label} ничего не запланировано."
        header = f"Записи на {label}:"
        shown = events[:LIST_LIMIT]
        content = f"{header}\n{format_event_list(shown, self.tz)}"
        if len(events) > len(shown):
            content += f"\n…и ещё {len(events) - len(shown)} записей."
        return content

    def _cache_key(self, period: Period, start: datetime, end: datetime, types: list[EventType] | None) -> str | None:
        type_key = ",".join(sorted(event_type.value for event_type in types)) if types else "all"
        return f"user:{self._user.id}:events:{period.value}:{start.isoformat()}:{end.isoformat()}:{type_key}"

    async def _invalidate_cache(self) -> None:
        if self._cache is not None:
            await self._cache.delete_prefix(f"user:{self._user.id}:")

    def _period(self, value: Any) -> Period:
        try:
            return Period(str(value or "week").lower())
        except ValueError:
            return Period.WEEK

    def _types(self, value: Any) -> list[EventType] | None:
        if not value:
            return None
        if isinstance(value, str):
            value = [value]
        result: list[EventType] = []
        for item in value:
            try:
                result.append(EventType(str(item).lower()))
            except ValueError:
                continue
        return result or None

    def _parse_arguments(self, raw: dict[str, Any] | str) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            return None
        text = raw.strip().strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
        try:
            parsed = json.loads(text or "{}")
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None

    @staticmethod
    def _int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _error(self, name: str, message: str) -> ToolResult:
        return ToolResult(name, f"{ERROR_PREFIX} {message}")
