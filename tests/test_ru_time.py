from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.ai.nlp.ru_time import apply_hint, looks_like_time, parse_temporal

MOSCOW = ZoneInfo("Europe/Moscow")
# Saturday, 31 October 2026, 19:08 — the weekday/date arithmetic that used to fail.
NOW = datetime(2026, 10, 31, 19, 8, tzinfo=MOSCOW)


@pytest.mark.parametrize(
    ("text", "expected_date", "expected_time"),
    [
        ("Напомни мне завтра в 10 утра позвонить Ивану", date(2026, 11, 1), time(10, 0)),
        ("В пятницу нужно отправить отчет", date(2026, 11, 6), None),
        ("В четверг в 11 у меня встреча с дизайнером", date(2026, 11, 5), time(11, 0)),
        ("Послезавтра встреча с юристом в 14:00", date(2026, 11, 2), time(14, 0)),
        ("Добавь встречу с командой завтра в 15:00", date(2026, 11, 1), time(15, 0)),
        ("Напомни через два часа проверить почту", date(2026, 10, 31), time(21, 8)),
        ("Перенеси встречу на 20.11", date(2026, 11, 20), None),
        ("Встреча 15 ноября в 12:30", date(2026, 11, 15), time(12, 30)),
        ("Планёрка каждый вторник в 10:00", date(2026, 11, 3), time(10, 0)),
        ("Позвонить в 9 вечера", date(2026, 10, 31), time(21, 0)),
        ("Обед в полдень", date(2026, 11, 1), time(12, 0)),
        ("Купить билеты до конца недели", date(2026, 11, 1), None),
        ("На следующей неделе сдать отчёт", date(2026, 11, 2), None),
    ],
)
def test_parse_temporal_resolves_russian_dates(text, expected_date, expected_time):
    hint = parse_temporal(text, NOW)

    assert hint.date == expected_date
    assert hint.time == expected_time


def test_weekday_is_the_next_occurrence_not_today():
    hint = parse_temporal("во вторник в 11 утра", NOW)

    assert hint.date == date(2026, 11, 3)
    assert hint.time == time(11, 0)


def test_bare_clock_time_keeps_the_day_inferred_from_the_clock():
    hint = parse_temporal("в 16:00", NOW)

    assert hint.time == time(16, 0)
    assert hint.date == date(2026, 11, 1)
    assert hint.explicit_date is False


def test_date_only_hint_is_explicit_and_has_no_time():
    hint = parse_temporal("Поставь встречу с Иваном завтра", NOW)

    assert hint.date == date(2026, 11, 1)
    assert hint.explicit_date is True
    assert hint.has_time is False


def test_segodnya_is_not_mistaken_for_a_clock_time():
    assert looks_like_time("Что у меня сегодня?") is False
    assert looks_like_time("Напомни в 10:30") is True
    assert looks_like_time("Позвонить вечером") is True


def test_apply_hint_replaces_a_wrong_weekday_from_the_model():
    wrong = datetime(2026, 11, 2, 11, 0, tzinfo=MOSCOW)  # model said Monday
    hint = parse_temporal("В четверг в 11 у меня встреча с дизайнером", NOW)

    assert apply_hint(wrong, hint) == datetime(2026, 11, 5, 11, 0, tzinfo=MOSCOW)


def test_apply_hint_keeps_the_day_when_only_a_clock_time_was_named():
    model_day = datetime(2026, 11, 5, 9, 0, tzinfo=MOSCOW)
    hint = parse_temporal("в 16:00", NOW)

    assert apply_hint(model_day, hint) == datetime(2026, 11, 5, 16, 0, tzinfo=MOSCOW)
