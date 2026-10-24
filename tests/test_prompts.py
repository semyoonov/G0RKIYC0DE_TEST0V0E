from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.ai.llm.prompts import build_system_prompt

MOSCOW = ZoneInfo("Europe/Moscow")


def test_prompt_names_today_tomorrow_and_weeks() -> None:
    prompt = build_system_prompt(MOSCOW, datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc))

    assert "Сейчас 25.10.2026, воскресенье, 12:00" in prompt
    assert "завтра 26.10.2026, понедельник" in prompt
    assert "послезавтра 27.10.2026, вторник" in prompt
    assert "эта неделя 19.10–25.10" in prompt
    assert "следующая 26.10–01.11" in prompt
    assert "не вычисляй их сам" in prompt


def test_prompt_marks_the_week_that_starts_on_monday() -> None:
    prompt = build_system_prompt(MOSCOW, datetime(2026, 10, 26, 6, 0, tzinfo=timezone.utc))

    assert "Сейчас 26.10.2026, понедельник, 09:00" in prompt
    assert "эта неделя 26.10–01.11" in prompt
