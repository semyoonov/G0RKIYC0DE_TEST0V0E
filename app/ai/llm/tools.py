from typing import Any

_DATETIME_HINT = (
    "Строка ISO 8601 с часовым поясом, например 2025-03-05T10:00:00+03:00. "
    "Не заполняй поле, если пользователь не назвал дату."
)
_PERIOD_VALUES = ["today", "tomorrow", "week", "all", "custom"]
_TYPE_VALUES = ["task", "meeting", "reminder"]

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "name": "create_task",
        "description": (
            "Создать задачу или напоминание пользователя. "
            "Используй для просьб вроде «напомни завтра в 10 позвонить Ивану», «купи билеты»."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Содержание задачи в инфинитиве, без даты и времени: «позвонить Ивану».",
                },
                "starts_at": {"type": "string", "description": f"Срок выполнения. {_DATETIME_HINT}"},
                "remind_at": {"type": "string", "description": f"Время, когда напомнить. {_DATETIME_HINT}"},
                "description": {"type": "string", "description": "Дополнительные детали, если пользователь их назвал."},
                "is_reminder": {
                    "type": "boolean",
                    "description": "true, если пользователь просит именно напомнить в конкретное время.",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "create_meeting",
        "description": "Создать встречу. Время и конкретное название обязательны: без них не вызывай инструмент, а спроси пользователя.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "С кем или о чём встреча: «с командой», «с дизайнером». Запрещено подставлять общее слово «Встреча» — если название не названо, спроси пользователя, как назвать встречу."},
                "starts_at": {"type": "string", "description": f"Начало встречи. {_DATETIME_HINT}"},
                "duration_minutes": {"type": "integer", "description": "Длительность в минутах, если названа."},
                "description": {"type": "string", "description": "Дополнительные детали."},
            },
            "required": ["title", "starts_at"],
        },
    },
    {
        "name": "list_events",
        "description": "Показать задачи и встречи за период: сегодня, завтра, текущая неделя, всё или свой интервал.",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "enum": _PERIOD_VALUES, "description": "Период выборки."},
                "date_from": {"type": "string", "description": "Начало своего интервала, ISO 8601 или YYYY-MM-DD."},
                "date_to": {"type": "string", "description": "Конец своего интервала, ISO 8601 или YYYY-MM-DD."},
                "types": {
                    "type": "array",
                    "items": {"type": "string", "enum": _TYPE_VALUES},
                    "description": "Ограничить типы записей.",
                },
            },
            "required": ["period"],
        },
    },
    {
        "name": "search_events",
        "description": "Найти ранее созданные записи по ключевым словам названия или описания.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Ключевые слова без служебных слов: «презентация», «Иван»."},
                "limit": {"type": "integer", "description": "Сколько записей вернуть, по умолчанию 5."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "update_event",
        "description": "Изменить название, время или описание существующей записи.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer", "description": "Идентификатор записи из list_events или search_events."},
                "title": {"type": "string", "description": "Новое название."},
                "starts_at": {"type": "string", "description": f"Новое время. {_DATETIME_HINT}"},
                "remind_at": {"type": "string", "description": f"Новое время напоминания. {_DATETIME_HINT}"},
                "description": {"type": "string", "description": "Новое описание."},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "complete_event",
        "description": "Отметить задачу выполненной или вернуть её в работу.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer", "description": "Идентификатор записи."},
                "done": {"type": "boolean", "description": "true — выполнено, false — вернуть в работу."},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "delete_event",
        "description": "Удалить запись пользователя.",
        "parameters": {
            "type": "object",
            "properties": {"event_id": {"type": "integer", "description": "Идентификатор записи."}},
            "required": ["event_id"],
        },
    },
]

TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS_SCHEMA)
