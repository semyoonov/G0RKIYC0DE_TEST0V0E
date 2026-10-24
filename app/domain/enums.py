from enum import Enum


class EventType(str, Enum):
    TASK = "task"
    MEETING = "meeting"
    REMINDER = "reminder"


class EventStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    CANCELLED = "cancelled"


class Platform(str, Enum):
    TELEGRAM = "telegram"
    VK = "vk"
    MAX = "max"
    WEB = "web"


class Period(str, Enum):
    TODAY = "today"
    TOMORROW = "tomorrow"
    WEEK = "week"
    ALL = "all"
    CUSTOM = "custom"


PLATFORM_TITLES: dict[Platform, str] = {
    Platform.TELEGRAM: "Telegram",
    Platform.VK: "ВКонтакте",
    Platform.MAX: "MAX",
    Platform.WEB: "Веб",
}

EVENT_TYPE_TITLES: dict[EventType, str] = {
    EventType.TASK: "задача",
    EventType.MEETING: "встреча",
    EventType.REMINDER: "напоминание",
}

EVENT_STATUS_TITLES: dict[EventStatus, str] = {
    EventStatus.PENDING: "не выполнено",
    EventStatus.DONE: "выполнено",
    EventStatus.CANCELLED: "отменено",
}
