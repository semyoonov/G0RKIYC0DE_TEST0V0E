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
            "Создать конкретную задачу или напоминание пользователя. "
            "Используй ТОЛЬКО когда пользователь назвал конкретное содержание (что сделать или о чём напомнить). "
            "Если содержание не названо (например, «поставь напоминание на 14:00», «напомни завтра»), "
            "НЕ вызывай инструмент, а спроси: «О чём тебе напомнить?»."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "weekday_named": {
                    "type": "string",
                    "enum": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
                    "description": "День недели, который пользователь назвал словами. Не заполняй, если дня недели в запросе не было.",
                },
                "time_named": {
                    "type": "boolean",
                    "description": "true, если пользователь сам назвал время («в 10», «в 15:00», «утра»); false, если время не звучало.",
                },
                "title": {
                    "type": "string",
                    "description": (
                        "Конкретное содержание задачи или напоминания в инфинитиве («позвонить Ивану», «купить билеты»). "
                        "Запрещено передавать общие слова («напоминание», «напомнить», «задача», «без названия»)."
                    ),
                },
                "starts_at": {"type": "string", "description": f"Срок выполнения. {_DATETIME_HINT}"},
                "remind_at": {"type": "string", "description": f"Время, когда напомнить. {_DATETIME_HINT}"},
                "rrule": {
                    "type": "string",
                    "description": (
                        "Правило повторения в формате iCalendar RRULE (RFC 5545), если названа периодичность. "
                        "Примеры: 'FREQ=WEEKLY;BYDAY=TU' (каждый вторник), 'FREQ=DAILY' (каждый день), "
                        "'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR' (по будням), 'FREQ=WEEKLY' (каждую неделю), 'FREQ=MONTHLY' (каждый месяц)."
                    ),
                },
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
                "weekday_named": {
                    "type": "string",
                    "enum": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
                    "description": "День недели, который пользователь назвал словами. Не заполняй, если дня недели в запросе не было.",
                },
                "time_named": {
                    "type": "boolean",
                    "description": "true, если пользователь сам назвал время («в 10», «в 15:00», «утра»); false, если время не звучало.",
                },
                "title": {"type": "string", "description": "С кем или о чём встреча: «с командой», «с дизайнером». Запрещено подставлять общее слово «Встреча» — если название не названо, спроси пользователя, как назвать встречу."},
                "starts_at": {"type": "string", "description": f"Начало встречи. {_DATETIME_HINT}"},
                "duration_minutes": {"type": "integer", "description": "Длительность в минутах, если названа."},
                "rrule": {
                    "type": "string",
                    "description": (
                        "Правило повторения в формате iCalendar RRULE (RFC 5545), если названа периодичность. "
                        "Примеры: 'FREQ=WEEKLY;BYDAY=TU' (каждый вторник), 'FREQ=DAILY' (каждый день), "
                        "'FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR' (по будням)."
                    ),
                },
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
        "description": "Изменить название, время или описание существующей записи по id или названию.",
        "parameters": {
            "type": "object",
            "properties": {
                "weekday_named": {
                    "type": "string",
                    "enum": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
                    "description": "День недели, который пользователь назвал словами. Не заполняй, если дня недели в запросе не было.",
                },
                "time_named": {
                    "type": "boolean",
                    "description": "true, если пользователь сам назвал время («в 10», «в 15:00», «утра»); false, если время не звучало.",
                },
                "event_id": {"type": "integer", "description": "Идентификатор записи из list_events или search_events."},
                "query": {"type": "string", "description": "Текущее название или ключевые слова записи, если id неизвестен."},
                "title": {"type": "string", "description": "Новое название."},
                "starts_at": {"type": "string", "description": f"Новое время. {_DATETIME_HINT}"},
                "remind_at": {"type": "string", "description": f"Новое время напоминания. {_DATETIME_HINT}"},
                "rrule": {"type": "string", "description": "Новое правило повторения RRULE или null для отмены повторения."},
                "description": {"type": "string", "description": "Новое описание."},
            },
        },
    },
    {
        "name": "complete_event",
        "description": "Отметить задачу выполненной или вернуть её в работу по id или названию.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer", "description": "Идентификатор записи, если известен."},
                "query": {"type": "string", "description": "Суть названия записи для выполнения («поесть», «купить молоко»), если id неизвестен."},
                "done": {"type": "boolean", "description": "true — выполнено, false — вернуть в работу."},
            },
        },
    },
    {
        "name": "delete_event",
        "description": "Удалить запись пользователя по идентификатору или названию/запросу.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer", "description": "Идентификатор записи, если известен."},
                "query": {"type": "string", "description": "Суть названия записи для удаления («поесть», «созвон с Васей»), если id неизвестен."},
            },
        },
    },
]

TOOL_NAMES = frozenset(tool["name"] for tool in TOOLS_SCHEMA)
