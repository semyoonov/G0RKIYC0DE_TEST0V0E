from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.timeutils import ensure_aware, format_datetime, utcnow
from app.domain.enums import EVENT_TYPE_TITLES, EventStatus
from app.domain.models import EventRead

_WEEKDAYS_RU = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def _human_day(moment: datetime) -> str:
    return f"{moment.strftime('%d.%m.%Y')}, {_WEEKDAYS_RU[moment.weekday()]}"


def build_system_prompt(tz: ZoneInfo, now: datetime | None = None) -> str:
    current = ensure_aware(now or utcnow()).astimezone(tz)
    human = f"{_human_day(current)}, {current.strftime('%H:%M')}"
    tomorrow = current + timedelta(days=1)
    after_tomorrow = current + timedelta(days=2)
    week_start = current - timedelta(days=current.weekday())
    next_week_start = week_start + timedelta(days=7)
    return (
        "Ты — ассистент, который ведёт личные задачи, напоминания и встречи пользователя.\n"
        f"Сейчас {human} (часовой пояс {tz.key}).\n"
        f"Опорные даты: сегодня {_human_day(current)}, завтра {_human_day(tomorrow)}, "
        f"послезавтра {_human_day(after_tomorrow)}; эта неделя {week_start.strftime('%d.%m')}–"
        f"{(week_start + timedelta(days=6)).strftime('%d.%m')}, следующая {next_week_start.strftime('%d.%m')}–"
        f"{(next_week_start + timedelta(days=6)).strftime('%d.%m')}. "
        "Бери даты из этого списка, не вычисляй их сам.\n\n"
        "Правила:\n"
        "1. Данные о событиях бери только из инструментов. Не придумывай события и их идентификаторы.\n"
        "2. Относительные даты («завтра», «в пятницу», «через час») переводи в абсолютные от текущего момента "
        "и передавай в ISO 8601 с часовым поясом. Для «завтра» бери дату из опорных дат: неверный месяц или год "
        "хуже, чем пропущенное поле.\n"
        "3. Встреча без времени не создаётся: если время не названо, задай один короткий вопрос и не вызывай инструмент.\n"
        "4. Задачу можно создать без даты. Напоминание требует времени напоминания.\n"
        "5. Если ответ инструмента начинается с «ОШИБКА», не пересказывай её пользователю: задай уточняющий вопрос "
        "или исправь аргументы и вызови инструмент снова.\n"
        "6. Подтверждая создание, назови тип записи, её содержание и время.\n"
        "7. Отвечай по-русски и коротко: одна-три фразы. Ответ читается вслух, поэтому без markdown, эмодзи "
        "и символов вроде «*» и «#». Перечисляя несколько событий, называй каждое с новой строки.\n"
        "8. Не упоминай инструменты, идентификаторы и служебные детали.\n"
        "9. Чтобы изменить, выполнить или удалить запись, сначала найди её через search_events.\n"
    )


def format_event_line(event: EventRead, tz: ZoneInfo, *, with_id: bool = True) -> str:
    if event.starts_at is not None:
        moment = format_datetime(event.starts_at, tz)
    elif event.remind_at is not None:
        moment = format_datetime(event.remind_at, tz)
    else:
        moment = "без даты"
    line = f"{moment} — {EVENT_TYPE_TITLES[event.type]}: {event.title}"
    if event.status is EventStatus.DONE:
        line += " (выполнено)"
    if event.description:
        line += f" ({event.description.splitlines()[0]})"
    if with_id:
        line += f" [id {event.id}]"
    return line


def format_event_list(
    events: list[EventRead],
    tz: ZoneInfo,
    *,
    empty_text: str = "На этот период ничего не запланировано.",
    with_id: bool = True,
) -> str:
    if not events:
        return empty_text
    return "\n".join(format_event_line(event, tz, with_id=with_id) for event in events)
