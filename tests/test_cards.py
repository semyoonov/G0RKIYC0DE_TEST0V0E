from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.domain.enums import EventStatus, EventType
from app.domain.models import EventRead
from app.interfaces.cards import (
    ACTION_LABELS,
    DESCRIPTION_LIMIT,
    DONE_BUTTON_LIMIT,
    action_label,
    cards_html,
    cards_text,
    done_button,
    event_card_html,
    event_card_text,
    parse_done_callback,
    pending_events,
)

MOSCOW = ZoneInfo("Europe/Moscow")
UTC = timezone.utc
CREATED_AT = datetime(2025, 3, 1, 9, 0, tzinfo=UTC)


def make_event(
    event_id: int = 1,
    *,
    event_type: EventType = EventType.REMINDER,
    title: str = "Позвонить Ивану",
    description: str | None = None,
    starts_at: datetime | None = None,
    remind_at: datetime | None = None,
    status: EventStatus = EventStatus.PENDING,
) -> EventRead:
    return EventRead(
        id=event_id,
        user_id=1,
        type=event_type,
        title=title,
        description=description,
        starts_at=starts_at,
        remind_at=remind_at,
        status=status,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )


def test_action_labels() -> None:
    assert ACTION_LABELS == {
        "create_task": "Создано",
        "create_meeting": "Создано",
        "update_event": "Изменено",
        "complete_event": "Выполнено",
        "delete_event": "Удалено",
    }


def test_action_label_only_for_actions() -> None:
    assert action_label("create_task") == "Создано"
    assert action_label("create_meeting") == "Создано"
    assert action_label("update_event") == "Изменено"
    assert action_label("complete_event") == "Выполнено"
    assert action_label("delete_event") == "Удалено"
    assert action_label("list_events") is None
    assert action_label("search_events") is None
    assert action_label(None) is None
    assert action_label("unknown_tool") is None


def test_event_card_html_layout() -> None:
    event = make_event(1, starts_at=datetime(2021, 5, 14, 7, 30, tzinfo=UTC))

    assert event_card_html(event, MOSCOW) == (
        "<b>Напоминание</b> · не выполнено\n"
        "Позвонить Ивану\n"
        "🕒 14.05.2021 в 10:30"
    )


def test_event_card_text_layout() -> None:
    event = make_event(1, starts_at=datetime(2021, 5, 14, 7, 30, tzinfo=UTC))

    assert event_card_text(event, MOSCOW) == (
        "Напоминание · не выполнено\n"
        "Позвонить Ивану\n"
        "🕒 14.05.2021 в 10:30"
    )


def test_event_card_html_escapes_dynamic_values() -> None:
    event = make_event(
        1,
        title='<b>Позвонить & "Ивану"',
        description="<i>важно</i>",
        starts_at=datetime(2021, 5, 14, 7, 30, tzinfo=UTC),
    )

    card = event_card_html(event, MOSCOW)

    assert '&lt;b&gt;Позвонить &amp; "Ивану"' in card
    assert "&lt;i&gt;важно&lt;/i&gt;" in card
    assert "<b>Позвонить" not in card
    assert "<i>важно" not in card


def test_event_card_text_keeps_raw_values() -> None:
    event = make_event(1, title="<b>Позвонить & Ивану", description="<i>важно</i>")

    card = event_card_text(event, MOSCOW)

    assert "<b>Позвонить & Ивану" in card
    assert "<i>важно</i>" in card
    assert "&lt;" not in card


def test_event_card_without_time() -> None:
    event = make_event(1)

    assert event_card_html(event, MOSCOW).endswith("\n🕒 без срока")
    assert event_card_text(event, MOSCOW).endswith("\n🕒 без срока")


def test_event_card_prefers_starts_at_over_remind_at() -> None:
    event = make_event(
        1,
        starts_at=datetime(2021, 5, 14, 7, 30, tzinfo=UTC),
        remind_at=datetime(2021, 5, 13, 6, 0, tzinfo=UTC),
    )

    assert "🕒 14.05.2021 в 10:30" in event_card_text(event, MOSCOW)


def test_event_card_falls_back_to_remind_at() -> None:
    event = make_event(1, remind_at=datetime(2021, 5, 14, 6, 15, tzinfo=UTC))

    assert "🕒 14.05.2021 в 09:15" in event_card_html(event, MOSCOW)


def test_event_card_localises_time() -> None:
    event = make_event(1, starts_at=datetime(2021, 1, 1, 21, 15, tzinfo=UTC))

    assert "02.01.2021 в 00:15" in event_card_html(event, MOSCOW)


def test_event_card_type_titles_are_capitalised() -> None:
    expected = {
        EventType.TASK: "<b>Задача</b> · не выполнено",
        EventType.MEETING: "<b>Встреча</b> · не выполнено",
        EventType.REMINDER: "<b>Напоминание</b> · не выполнено",
    }

    for event_type, header in expected.items():
        card = event_card_html(make_event(1, event_type=event_type), MOSCOW)
        assert card.splitlines()[0] == header


def test_event_card_status_title() -> None:
    event = make_event(1, status=EventStatus.DONE)

    assert event_card_html(event, MOSCOW).splitlines()[0] == "<b>Напоминание</b> · выполнено"
    assert " · отменено" in event_card_html(make_event(2, status=EventStatus.CANCELLED), MOSCOW)


def test_short_description_is_rendered() -> None:
    event = make_event(1, description="взять паспорт и договор")

    assert event_card_html(event, MOSCOW).splitlines()[-1] == "взять паспорт и договор"
    assert event_card_text(event, MOSCOW).splitlines()[-1] == "взять паспорт и договор"


def test_description_at_limit_is_rendered() -> None:
    description = "я" * DESCRIPTION_LIMIT
    event = make_event(1, description=description)

    assert event_card_text(event, MOSCOW).splitlines()[-1] == description


def test_long_description_is_skipped() -> None:
    description = "я" * (DESCRIPTION_LIMIT + 1)
    event = make_event(1, description=description)

    assert description not in event_card_text(event, MOSCOW)
    assert len(event_card_text(event, MOSCOW).splitlines()) == 3


def test_blank_description_is_skipped() -> None:
    event = make_event(1, description="   ")

    assert len(event_card_text(event, MOSCOW).splitlines()) == 3


def test_done_button_only_for_pending() -> None:
    assert done_button(make_event(7, status=EventStatus.PENDING)) == ("✅ Выполнено", "event:done:7")
    assert done_button(make_event(7, status=EventStatus.DONE)) is None
    assert done_button(make_event(7, status=EventStatus.CANCELLED)) is None


def test_pending_events_limits_and_filters() -> None:
    events = [make_event(index) for index in range(1, 9)]
    events.append(make_event(9, status=EventStatus.DONE))

    pending = pending_events(events)

    assert len(pending) == DONE_BUTTON_LIMIT
    assert [event.id for event in pending] == [1, 2, 3, 4, 5]


def test_cards_html_joins_cards_with_blank_line() -> None:
    first = make_event(1, starts_at=datetime(2021, 5, 14, 7, 30, tzinfo=UTC))
    second = make_event(2, event_type=EventType.TASK, title="Позвонить в банк")

    message = cards_html([first, second], MOSCOW, action_label("create_task"))

    assert message == (
        "<b>Создано</b>\n\n"
        f"{event_card_html(first, MOSCOW)}\n\n"
        f"{event_card_html(second, MOSCOW)}"
    )
    assert message.count("\n\n") == 2


def test_cards_text_with_action() -> None:
    first = make_event(1, starts_at=datetime(2021, 5, 14, 7, 30, tzinfo=UTC))
    second = make_event(2, event_type=EventType.TASK, title="Позвонить в банк")

    message = cards_text([first, second], MOSCOW, action_label("create_meeting"))

    assert message == (
        "Создано\n\n"
        f"{event_card_text(first, MOSCOW)}\n\n"
        f"{event_card_text(second, MOSCOW)}"
    )
    assert "<b>" not in message


def test_cards_without_action() -> None:
    event = make_event(1, starts_at=datetime(2021, 5, 14, 7, 30, tzinfo=UTC))

    assert cards_html([event], MOSCOW) == event_card_html(event, MOSCOW)
    assert cards_text([event], MOSCOW) == event_card_text(event, MOSCOW)
    assert cards_html([event], MOSCOW, action_label("list_events")) == event_card_html(event, MOSCOW)


def test_cards_without_events() -> None:
    assert cards_html([], MOSCOW) == ""
    assert cards_text([], MOSCOW) == ""
    assert cards_html([], MOSCOW, "Создано") == "<b>Создано</b>"
    assert cards_text([], MOSCOW, "Создано") == "Создано"


def test_cards_escape_action_label() -> None:
    assert cards_html([], MOSCOW, "A & B") == "<b>A &amp; B</b>"
    assert cards_text([], MOSCOW, "A & B") == "A & B"


def test_parse_done_callback() -> None:
    assert parse_done_callback("event:done:7") == 7
    assert parse_done_callback("event:done:1234") == 1234
    assert parse_done_callback("event:done:") is None
    assert parse_done_callback("event:done:abc") is None
    assert parse_done_callback("event:done:0") is None
    assert parse_done_callback("event:done:-3") is None
    assert parse_done_callback("event:delete:7") is None
    assert parse_done_callback("") is None
    assert parse_done_callback(None) is None
