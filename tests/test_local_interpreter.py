from datetime import datetime, timedelta, timezone

import pytest

from app.ai.llm.local_interpreter import LocalInterpreter

MOSCOW = timezone(timedelta(hours=3))
MONDAY = datetime(2025, 3, 3, 10, 0, tzinfo=MOSCOW)


@pytest.fixture
def interpreter() -> LocalInterpreter:
    return LocalInterpreter(MOSCOW)


def test_reminder_with_relative_day_and_time(interpreter):
    action = interpreter.interpret("Напомни мне завтра в 10 утра позвонить Ивану", now=MONDAY)

    assert action is not None
    assert action.tool == "create_task"
    assert action.arguments["title"] == "Позвонить Ивану"
    assert action.arguments["is_reminder"] is True
    assert action.arguments["starts_at"] == datetime(2025, 3, 4, 10, 0, tzinfo=MOSCOW).isoformat()


def test_task_on_weekday_without_time(interpreter):
    action = interpreter.interpret("В пятницу нужно отправить отчет", now=MONDAY)

    assert action is not None
    assert action.tool == "create_task"
    assert action.arguments["title"] == "Отправить отчет"
    assert action.arguments["starts_at"] == datetime(2025, 3, 7, 23, 59, tzinfo=MOSCOW).isoformat()


def test_task_with_end_of_week_deadline(interpreter):
    action = interpreter.interpret("Поставь задачу купить билеты до конца недели", now=MONDAY)

    assert action is not None
    assert action.arguments["title"] == "Купить билеты"
    assert action.arguments["starts_at"] == datetime(2025, 3, 9, 23, 59, tzinfo=MOSCOW).isoformat()


def test_meeting_with_relative_time(interpreter):
    action = interpreter.interpret("Добавь встречу с командой завтра в 15:00", now=MONDAY)

    assert action is not None
    assert action.tool == "create_meeting"
    assert action.arguments["title"] == "Встреча с командой"
    assert action.arguments["starts_at"] == datetime(2025, 3, 4, 15, 0, tzinfo=MOSCOW).isoformat()


def test_meeting_in_another_word_order(interpreter):
    action = interpreter.interpret("В четверг в 11 у меня встреча с дизайнером", now=MONDAY)

    assert action is not None
    assert action.tool == "create_meeting"
    assert action.arguments["title"] == "Встреча с дизайнером"
    assert action.arguments["starts_at"] == datetime(2025, 3, 6, 11, 0, tzinfo=MONDAY.tzinfo).isoformat()


def test_meeting_without_time_asks_executor_for_time(interpreter):
    action = interpreter.interpret("Добавь встречу с командой завтра", now=MONDAY)

    assert action is not None
    assert action.tool == "create_meeting"
    assert "starts_at" not in action.arguments


@pytest.mark.parametrize(
    ("text", "period"),
    [
        ("Что у меня сегодня?", "today"),
        ("Какие задачи у меня на завтра?", "tomorrow"),
        ("Что запланировано на эту неделю?", "week"),
        ("Покажи список встреч", "week"),
    ],
)
def test_list_intents(interpreter, text, period):
    action = interpreter.interpret(text, now=MONDAY)
    assert action is not None
    assert action.tool == "list_events"
    assert action.arguments["period"] == period


def test_search_intent_strips_command_words(interpreter):
    action = interpreter.interpret("Найди задачу про презентацию", now=MONDAY)

    assert action is not None
    assert action.tool == "search_events"
    assert action.arguments["query"] == "презентацию"


def test_search_keeps_person_name(interpreter):
    action = interpreter.interpret("Когда у меня была встреча с Иваном?", now=MONDAY)

    assert action is not None
    assert action.tool == "search_events"
    assert "Иваном" in action.arguments["query"]


def test_complete_and_delete_by_id(interpreter):
    completed = interpreter.interpret("Выполнил 12", now=MONDAY)
    assert completed is not None
    assert completed.tool == "complete_event"
    assert completed.arguments == {"event_id": 12}

    deleted = interpreter.interpret("Удали запись 7", now=MONDAY)
    assert deleted is not None
    assert deleted.tool == "delete_event"
    assert deleted.arguments == {"event_id": 7}


@pytest.mark.parametrize("text", ["Привет", "", "Как дела?"])
def test_unrelated_text_is_not_interpreted(interpreter, text):
    assert interpreter.interpret(text, now=MONDAY) is None
