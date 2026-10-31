"""Refuse requests that are outside the assistant's product scope.

The assistant manages tasks, meetings and reminders. Users still try to use it
as a general chat model ("give me a pie recipe", "ignore your instructions"),
so the scope check happens before the model is called and cannot be talked
around by prompt injection.
"""

from __future__ import annotations

import re

from app.ai.nlp.ru_time import normalize

OFF_TOPIC_REPLY = (
    "Я помогаю только с задачами, встречами и напоминаниями. "
    "Скажите, что запланировать, — например: «Напомни завтра в 10 позвонить Ивану»."
)

_PATTERNS = (
    re.compile(
        r"(?:дай|расскажи|подскажи|скинь|напиши|придумай|сгенерируй|сочини)\s+(?:мне\s+)?"
        r"(?:рецепт|стих|анекдот|шутк|сказк|сочинени|песн|поздравлени|тост|эссе)"
    ),
    re.compile(r"(?:как|что)\s+(?:приготовить|испечь|сварить|запечь)"),
    re.compile(
        r"(?:игнорируй|забудь|отмени|обойди|обойди)\s+(?:все\s+|свои\s+|предыдущие\s+|эти\s+)*"
        r"(?:инструкции|правила|ограничения|промпт|указания)"
    ),
    re.compile(r"(?:system\s+prompt|системн\w*\s+промпт|твои?\s+инструкции|твой\s+промпт)"),
    re.compile(r"(?:какие|покажи)\s+(?:у\s+тебя\s+)?(?:правила|инструкции|промпт)"),
    re.compile(
        r"(?:напиши|сгенерируй|создай)\s+(?:мне\s+)?(?:код|программу|скрипт|сочинение|статью|письмо|доклад)"
    ),
    re.compile(r"(?:переведи|сделай\s+перевод)\s"),
    re.compile(r"(?:расскажи|объясни)\s+(?:анекдот|шутку|сказку|историю|фильм)"),
    re.compile(r"(?:кто|что)\s+ты\s+(?:такое|за\s+модель)|какая\s+ты\s+модель"),
)


def is_off_topic(text: str) -> bool:
    normalized = normalize(text)
    return any(pattern.search(normalized) for pattern in _PATTERNS)
