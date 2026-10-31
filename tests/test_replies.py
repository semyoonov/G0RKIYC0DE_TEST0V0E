from app.ai.llm.replies import has_call_syntax, recover_calls, sanitize_reply

LEAKED = (
    "list_events [\n"
    "    <|superquote|>date_from<|superquote|>: <|superquote|>2026-11-01<|superquote|>,\n"
    "    <|superquote|>date_to<|superquote|>: <|superquote|>2026-11-01<|superquote|>,\n"
    "    <|superquote|>period<|superquote|>: <|superquote|>tomorrow<|superquote|>\n"
    "] На завтра у тебя запланирована задача «купить билеты»."
)
QUOTED = 'create_meeting [\n    "starts_at": "2026-11-01T16:00:00+03:00",\n    "title": "с Иваном"\n] Встреча запланирована.'


def test_recover_calls_parses_superquote_serialisation():
    calls, cleaned = recover_calls(LEAKED)

    assert len(calls) == 1
    assert calls[0].name == "list_events"
    assert calls[0].arguments["period"] == "tomorrow"
    assert "list_events" not in cleaned
    assert "купить билеты" in cleaned


def test_recover_calls_parses_plain_json_serialisation():
    calls, cleaned = recover_calls(QUOTED)

    assert calls[0].name == "create_meeting"
    assert calls[0].arguments["starts_at"] == "2026-11-01T16:00:00+03:00"
    assert calls[0].arguments["title"] == "с Иваном"
    assert "<|superquote|>" not in cleaned


def test_recover_calls_returns_nothing_for_normal_prose():
    calls, cleaned = recover_calls("Завтра в 10:00 — напоминание: позвонить Ивану.")

    assert calls == []
    assert cleaned == "Завтра в 10:00 — напоминание: позвонить Ивану."


def test_sanitize_strips_call_syntax_and_service_tokens():
    cleaned = sanitize_reply(LEAKED)

    assert "list_events" not in cleaned
    assert "<|superquote|>" not in cleaned
    assert cleaned == "На завтра у тебя запланирована задача «купить билеты»."


def test_sanitize_drops_english_narration_and_markdown():
    cleaned = sanitize_reply("Create a task «проверить почту» with reminder at 21:07.\n**Готово.**\n- Напоминание создано.")

    assert "Create a task" not in cleaned
    assert "**" not in cleaned
    assert "Напоминание создано." in cleaned


def test_sanitize_keeps_normal_russian_text_intact():
    text = "Встреча «с командой» добавлена на завтра в 15:00."

    assert sanitize_reply(text) == text
    assert has_call_syntax(text) is False
