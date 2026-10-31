from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.domain.enums import Period

UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def to_db(value: datetime) -> datetime:
    """Naive-UTC значение в том виде, в каком оно лежит в базе."""
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).replace(tzinfo=None)


def from_db(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def to_local(value: datetime | None, tz: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    return ensure_aware(value).astimezone(tz)


def start_of_day(value: datetime, tz: ZoneInfo) -> datetime:
    local = ensure_aware(value).astimezone(tz)
    return datetime.combine(local.date(), time.min, tzinfo=tz)


def period_bounds(period: Period, tz: ZoneInfo, now: datetime | None = None, days: int = 7) -> tuple[datetime, datetime]:
    """Границы периода [начало, конец) в часовом поясе пользователя."""
    current = ensure_aware(now or datetime.now(UTC)).astimezone(tz)
    today = start_of_day(current, tz)
    if period is Period.TODAY:
        return today, today + timedelta(days=1)
    if period is Period.TOMORROW:
        return today + timedelta(days=1), today + timedelta(days=2)
    if period is Period.WEEK:
        monday = today - timedelta(days=today.weekday())
        return monday, monday + timedelta(days=7)
    if period is Period.ALL:
        return today - timedelta(days=3650), today + timedelta(days=3650)
    return today, today + timedelta(days=days)


def format_datetime(value: datetime, tz: ZoneInfo, now: datetime | None = None) -> str:
    local = to_local(value, tz)
    assert local is not None
    current = ensure_aware(now or datetime.now(UTC)).astimezone(tz)
    delta_days = (local.date() - current.date()).days
    if delta_days == 0:
        prefix = "сегодня"
    elif delta_days == 1:
        prefix = "завтра"
    elif delta_days == -1:
        prefix = "вчера"
    elif 1 < delta_days < 7:
        prefix = _WEEKDAYS[local.weekday()]
    else:
        prefix = local.strftime("%d.%m.%Y")
    return f"{prefix} в {local.strftime('%H:%M')}"


_WEEKDAYS = ("в понедельник", "во вторник", "в среду", "в четверг", "в пятницу", "в субботу", "в воскресенье")
