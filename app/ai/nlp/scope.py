"""Refuse requests that are outside the assistant's product scope.

A short phrase list catches the obvious attempts before the model is called;
everything subtler is left to the prompt, which states the same boundary.
"""

from __future__ import annotations

OFF_TOPIC_REPLY = (
    "Я помогаю только с задачами, встречами и напоминаниями. "
    "Скажите, что запланировать, — например: «Напомни завтра в 10 позвонить Ивану»."
)

_OFF_TOPIC = (
    "дай рецепт",
    "расскажи рецепт",
    "как приготовить",
    "как испечь",
    "расскажи анекдот",
    "расскажи стих",
    "напиши стих",
    "напиши код",
    "напиши программу",
    "переведи ",
)
_INJECTION = (
    "игнорируй инструкции",
    "игнорируй все инструкции",
    "забудь инструкции",
    "system prompt",
    "системный промпт",
    "покажи промпт",
    "твои инструкции",
    "твои правила",
)


def normalize(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def is_off_topic(text: str) -> bool:
    normalized = normalize(text)
    return any(phrase in normalized for phrase in _OFF_TOPIC + _INJECTION)
