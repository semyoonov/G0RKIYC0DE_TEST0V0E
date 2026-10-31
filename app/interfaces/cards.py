"""Общая отрисовка карточек выполненных действий для чат-интерфейсов."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape
from zoneinfo import ZoneInfo

from app.core.timeutils import format_datetime
from app.domain.enums import EVENT_STATUS_TITLES, EVENT_TYPE_TITLES, EventStatus
from app.domain.models import EventRead

ACTION_LABELS: dict[str, str] = {
    "create_task": "Создано",
    "create_meeting": "Создано",
    "update_event": "Изменено",
    "complete_event": "Выполнено",
    "delete_event": "Удалено",
}

DONE_CALLBACK_PREFIX = "event:done:"
DONE_BUTTON_TEXT = "✅ Выполнено"
DONE_BUTTON_LIMIT = 5
DESCRIPTION_LIMIT = 120
NO_TIME_LINE = "🕒 без срока"
_TIME_PREFIX = "🕒"
_HEADER_SEPARATOR = " · "


def action_label(intent: str | None) -> str | None:
    return ACTION_LABELS.get(intent) if intent else None


def _type_title(event: EventRead) -> str:
    title = EVENT_TYPE_TITLES.get(event.type)
    return title.capitalize() if title else str(event.type)


def _status_title(event: EventRead) -> str:
    return EVENT_STATUS_TITLES.get(event.status, str(event.status))


def _description(event: EventRead) -> str | None:
    description = " ".join((event.description or "").split())
    return description if description and len(description) <= DESCRIPTION_LIMIT else None


def _time_line(event: EventRead, tz: ZoneInfo) -> str:
    when = event.starts_at or event.remind_at
    if when is None:
        return NO_TIME_LINE
    return f"{_TIME_PREFIX} {format_datetime(when, tz)}"


def _card_lines(event: EventRead, tz: ZoneInfo) -> list[str]:
    header = f"{_type_title(event)}{_HEADER_SEPARATOR}{_status_title(event)}"
    lines = [header, event.title, _time_line(event, tz)]
    description = _description(event)
    if description is not None:
        lines.append(description)
    return lines


def event_card_html(event: EventRead, tz: ZoneInfo) -> str:
    header = (
        f"<b>{escape(_type_title(event), quote=False)}</b>"
        f"{_HEADER_SEPARATOR}{escape(_status_title(event), quote=False)}"
    )
    lines = [header, escape(event.title, quote=False), escape(_time_line(event, tz), quote=False)]
    description = _description(event)
    if description is not None:
        lines.append(escape(description, quote=False))
    return "\n".join(lines)


def event_card_text(event: EventRead, tz: ZoneInfo) -> str:
    return "\n".join(_card_lines(event, tz))


def done_button(event: EventRead) -> tuple[str, str] | None:
    if event.status is not EventStatus.PENDING:
        return None
    return DONE_BUTTON_TEXT, f"{DONE_CALLBACK_PREFIX}{event.id}"


def parse_done_callback(data: str | None) -> int | None:
    """Id записи из payload кнопки «Готово»; None, если он битый."""
    if not isinstance(data, str) or not data.startswith(DONE_CALLBACK_PREFIX):
        return None
    raw = data[len(DONE_CALLBACK_PREFIX):]
    try:
        event_id = int(raw)
    except ValueError:
        return None
    return event_id if event_id > 0 else None


def pending_events(events: Sequence[EventRead], limit: int = DONE_BUTTON_LIMIT) -> list[EventRead]:
    return [event for event in events if event.status is EventStatus.PENDING][:limit]


def _with_action(body: str, action_line: str | None) -> str:
    if action_line is None:
        return body
    return f"{action_line}\n\n{body}" if body else action_line


def cards_html(events: Sequence[EventRead], tz: ZoneInfo, action: str | None = None) -> str:
    body = "\n\n".join(event_card_html(event, tz) for event in events)
    action_line = f"<b>{escape(action, quote=False)}</b>" if action else None
    return _with_action(body, action_line)


def cards_text(events: Sequence[EventRead], tz: ZoneInfo, action: str | None = None) -> str:
    body = "\n\n".join(event_card_text(event, tz) for event in events)
    return _with_action(body, action or None)


__all__ = [
    "ACTION_LABELS",
    "DESCRIPTION_LIMIT",
    "DONE_BUTTON_LIMIT",
    "DONE_BUTTON_TEXT",
    "DONE_CALLBACK_PREFIX",
    "NO_TIME_LINE",
    "action_label",
    "cards_html",
    "cards_text",
    "done_button",
    "event_card_html",
    "event_card_text",
    "parse_done_callback",
    "pending_events",
]
