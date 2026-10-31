"""Не даёт синтаксису вызова инструмента попасть в текст, который читает пользователь.

GigaChat иногда отвечает сериализованным вызовом функции в `content`, а не в поле
`function_call`, порой в кавычках `<|superquote|>`. Без обработки этот текст уходит
пользователю и переигрывается в истории диалога — и модель закрепляет привычку.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.ai.llm.tools import TOOLS_SCHEMA

_TOOL_NAMES = tuple(sorted({str(item["name"]) for item in TOOLS_SCHEMA}, key=len, reverse=True))
_CALL_BLOCK = re.compile(
    r"(?P<name>" + "|".join(_TOOL_NAMES) + r")\s*\[\s*(?P<body>.*?)\s*\]",
    re.DOTALL,
)
_QUOTE_TOKENS = re.compile(r"<\|[a-z_]+\|>")
_ENGLISH_NARRATION = re.compile(
    r"^(?:create|add|update|delete|remove|list|search|call|set|schedule|complete|find)\b.*$",
    re.IGNORECASE,
)
_MARKDOWN_BOLD = re.compile(r"\*\*(.+?)\*\*")
_BULLET = re.compile(r"(?m)^\s*[*-]\s+")


@dataclass(frozen=True)
class RecoveredCall:
    name: str
    arguments: dict[str, Any]


def _parse_body(body: str) -> dict[str, Any] | None:
    cleaned = body.replace("<|superquote|>", '"').strip()
    if not cleaned:
        return None
    if ":" not in cleaned:
        return None
    if not cleaned.lstrip().startswith('"'):
        cleaned = re.sub(r"(?<![\w\"])([A-Za-z_][A-Za-z0-9_]*)\s*:", r'"\1":', cleaned)
    try:
        value = json.loads("{" + cleaned + "}")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def recover_calls(text: str) -> tuple[list[RecoveredCall], str]:
    """Отделяет утёкший вызов функции от текста ответа."""
    calls: list[RecoveredCall] = []
    if not text:
        return calls, text
    for match in list(_CALL_BLOCK.finditer(text)):
        arguments = _parse_body(match.group("body"))
        if arguments is None:
            continue
        calls.append(RecoveredCall(name=match.group("name"), arguments=arguments))
    cleaned = _CALL_BLOCK.sub(" ", text) if calls else text
    return calls, cleaned


def sanitize_reply(text: str) -> str:
    """Убирает синтаксис вызовов, служебные токены, английские пояснения и разметку."""
    if not text:
        return ""
    cleaned = _CALL_BLOCK.sub(" ", text)
    cleaned = _QUOTE_TOKENS.sub("", cleaned)
    lines = [line for line in cleaned.splitlines() if not _ENGLISH_NARRATION.match(line.strip())]
    cleaned = "\n".join(lines)
    cleaned = _MARKDOWN_BOLD.sub(r"\1", cleaned)
    cleaned = _BULLET.sub("", cleaned)
    cleaned = cleaned.replace("**", "").replace("`", "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"^[\s,;:]+", "", cleaned)
    return cleaned.strip()


def has_call_syntax(text: str) -> bool:
    return bool(_QUOTE_TOKENS.search(text) or _CALL_BLOCK.search(text))
