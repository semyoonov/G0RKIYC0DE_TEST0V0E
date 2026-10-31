import re
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from app.core.timeutils import to_db, utcnow
from app.db.models.account_link import AccountLink
from app.db.models.event import Event
from app.db.models.user import User
from app.domain.enums import EventStatus, EventType, Platform
from app.domain.models import EventCreate, EventUpdate
from app.repositories.base import BaseRepository

_WORD_RE = re.compile(r"[\w\-]+", re.UNICODE)
_SEARCH_STOPWORDS = frozenset(
    {
        "а",
        "без",
        "бы",
        "был",
        "была",
        "были",
        "было",
        "в",
        "во",
        "все",
        "всё",
        "где",
        "для",
        "до",
        "его",
        "ее",
        "её",
        "если",
        "есть",
        "же",
        "задач",
        "задача",
        "задачи",
        "задачу",
        "записи",
        "запись",
        "и",
        "или",
        "к",
        "как",
        "какая",
        "какие",
        "когда",
        "ко",
        "ли",
        "мне",
        "на",
        "найди",
        "напомни",
        "напоминание",
        "напоминания",
        "напоминаний",
        "встреча",
        "встречи",
        "встречу",
        "встреч",
        "удали",
        "удалить",
        "отмени",
        "отменить",
        "не",
        "но",
        "о",
        "об",
        "он",
        "она",
        "они",
        "от",
        "по",
        "покажи",
        "про",
        "с",
        "со",
        "у",
        "что",
        "чтобы",
        "это",
    }
)


_SYNONYMS: dict[str, tuple[str, ...]] = {
    "тз": ("техническое", "техзадание"),
    "техзадание": ("техническое",),
    "договор": ("контракт",),
    "контракт": ("договор",),
    "созвон": ("звонок", "позвонить"),
    "звонок": ("созвон", "позвонить"),
    "позвонить": ("созвон", "звонок"),
    "отчет": ("отчётность",),
    "отчетность": ("отчет",),
    "планерка": ("совещание",),
    "совещание": ("планерка",),
    "подготовить": ("сделать",),
    "подготовь": ("сделать", "подготовить"),
    "сделать": ("подготовить",),
    "купить": ("приобрести",),
    "приобрести": ("купить",),
    "презентация": ("презентацию", "доклад"),
    "доклад": ("презентация",),
    "встретиться": ("встреча",),
}


def _word_patterns(word: str) -> list[str]:
    spellings = {word, word.replace("е", "ё"), word.replace("ё", "е")}
    variants: list[str] = []
    for spelling in spellings:
        variants.extend([spelling, spelling.capitalize()])
        for cut in (1, 2, 3):
            if len(spelling) - cut >= 4:
                stem = spelling[:-cut]
                variants.extend([stem, stem.capitalize()])
    return variants


def _token_patterns(token: str) -> list[str]:
    variants: list[str] = []
    for word in (token, *_SYNONYMS.get(token, ())):
        variants.extend(_word_patterns(word))
    return [f"%{variant}%" for variant in dict.fromkeys(variants)]


def _token_words(token: str) -> tuple[str, ...]:
    return (token, *_SYNONYMS.get(token, ()))


_TYPE_WORDS = (
    (EventType.MEETING, ("встреч", "совещан", "созвон", "митинг")),
    (EventType.REMINDER, ("напомин", "напомн")),
    (EventType.TASK, ("задач", "дело", "дела", "сдел")),
)


def _type_from_query(query: str) -> EventType | None:
    lowered = query.lower().replace("ё", "е")
    for event_type, stems in _TYPE_WORDS:
        if any(stem in lowered for stem in stems):
            return event_type
    return None


class EventRepository(BaseRepository[Event]):
    model = Event

    async def get_for_user(self, user_id: int, event_id: int) -> Event | None:
        statement = select(Event).where(Event.id == event_id, Event.user_id == user_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def create(self, user_id: int, data: EventCreate, *, commit: bool = True) -> Event:
        """Insert an event; `commit=False` keeps it in the caller's transaction."""
        event = Event(
            user_id=user_id,
            type=data.type,
            title=data.title,
            description=data.description,
            starts_at=to_db(data.starts_at) if data.starts_at else None,
            remind_at=to_db(data.remind_at) if data.remind_at else None,
            rrule=data.rrule,
            status=data.status,
            source=data.source,
        )
        if commit:
            return await self.add(event)
        self.session.add(event)
        await self.session.flush()
        return event

    async def update(self, event: Event, data: EventUpdate) -> Event:
        payload = data.model_dump(exclude_unset=True)
        for datetime_field in ("starts_at", "remind_at"):
            if datetime_field in payload:
                value = payload[datetime_field]
                payload[datetime_field] = to_db(value) if value else None
        for field, value in payload.items():
            setattr(event, field, value)
        if "remind_at" in payload or payload.get("status") is EventStatus.PENDING:
            event.reminder_sent_at = None
        event.updated_at = to_db(utcnow())
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def mark_done(self, event: Event, done: bool = True) -> Event:
        event.status = EventStatus.DONE if done else EventStatus.PENDING
        if not done:
            event.reminder_sent_at = None
        event.updated_at = to_db(utcnow())
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def list_for_period(
        self,
        user_id: int,
        start: datetime,
        end: datetime,
        types: Sequence[EventType] | None = None,
        include_done: bool = True,
        include_undated: bool = False,
    ) -> list[Event]:
        statement = select(Event).where(Event.user_id == user_id, Event.status != EventStatus.CANCELLED)
        if include_undated:
            statement = statement.where(
                or_(
                    and_(Event.starts_at.is_not(None), Event.starts_at >= to_db(start), Event.starts_at < to_db(end)),
                    Event.starts_at.is_(None),
                )
            )
        else:
            statement = statement.where(
                Event.starts_at.is_not(None),
                Event.starts_at >= to_db(start),
                Event.starts_at < to_db(end),
            )
        if types:
            statement = statement.where(Event.type.in_(list(types)))
        if not include_done:
            statement = statement.where(Event.status == EventStatus.PENDING)
        statement = statement.order_by(Event.starts_at.is_(None), Event.starts_at.asc(), Event.id.asc())
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def search(
        self,
        user_id: int,
        query: str,
        limit: int = 10,
        include_done: bool = True,
    ) -> list[Event]:
        normalized_query = (query or "").lower().replace("ё", "е")
        tokens = [token for token in _WORD_RE.findall(normalized_query) if token not in _SEARCH_STOPWORDS]
        if not tokens:
            return []
        wanted_type = _type_from_query(query)

        base_filter = [
            Event.user_id == user_id,
            Event.status != EventStatus.CANCELLED,
        ]
        if not include_done:
            base_filter.append(Event.status == EventStatus.PENDING)

        token_conditions = []
        for token in tokens:
            patterns = _token_patterns(token)
            token_conditions.append(
                or_(
                    *(Event.title.ilike(pattern) for pattern in patterns),
                    *(Event.description.ilike(pattern) for pattern in patterns),
                )
            )

        # All words match: precise, so a wide window is cheap.
        statement = select(Event).where(*base_filter, and_(*token_conditions)).limit(max(limit * 10, 100))
        result = await self.session.execute(statement)
        matches = list(result.scalars().all())

        if not matches and len(tokens) > 1:
            # Fallback when the query carries words the record does not (weekdays, recurrence).
            statement = select(Event).where(*base_filter, or_(*token_conditions)).limit(max(limit * 20, 400))
            result = await self.session.execute(statement)
            matches = list(result.scalars().all())

        if not matches:
            return []
        return self._rank(matches, tokens, normalized_query, wanted_type)[:limit]

    @staticmethod
    def _rank(
        events: list[Event],
        tokens: list[str],
        query_lower: str,
        wanted_type: EventType | None,
    ) -> list[Event]:
        """Order by how well the record matches, never by how recent it is."""

        def score(event: Event) -> tuple[int, int, float]:
            title = (event.title or "").lower().replace("ё", "е")
            description = (event.description or "").lower().replace("ё", "е")
            value = 0
            for token in tokens:
                for word in _token_words(token):
                    stem = word[:-2] if len(word) > 5 else word
                    if stem in title:
                        value += 4
                        break
                    if stem in description:
                        value += 1
                        break
            if query_lower and query_lower in title:
                value += 6
            if wanted_type is not None and event.type is wanted_type:
                value += 3
            if event.status is EventStatus.PENDING:
                value += 1
            recency = event.starts_at.timestamp() if event.starts_at is not None else 0.0
            return (value, int(wanted_type is not None and event.type is wanted_type), recency)

        decorated = sorted(((score(event), event) for event in events), key=lambda pair: pair[0], reverse=True)
        return [event for _, event in decorated]

    async def upcoming(self, user_id: int, now: datetime | None = None, limit: int = 5) -> list[Event]:
        moment = to_db(now or utcnow())
        statement = (
            select(Event)
            .where(
                Event.user_id == user_id,
                Event.starts_at.is_not(None),
                Event.starts_at >= moment,
                Event.status == EventStatus.PENDING,
            )
            .order_by(Event.starts_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def due_reminders(
        self,
        now: datetime | None = None,
        lookahead_seconds: int = 0,
        limit: int = 50,
        platforms: Sequence[Platform] | None = None,
    ) -> list[Event]:
        moment = now or utcnow()
        upper = to_db(moment + timedelta(seconds=lookahead_seconds))
        lower = to_db(moment - timedelta(days=1))
        statement = (
            select(Event)
            .join(User, Event.user_id == User.id)
            .options(selectinload(Event.user).selectinload(User.links))
            .where(
                Event.remind_at.is_not(None),
                Event.remind_at >= lower,
                Event.remind_at <= upper,
                Event.reminder_sent_at.is_(None),
                Event.status == EventStatus.PENDING,
            )
        )
        if platforms:
            statement = statement.where(
                or_(
                    User.platform.in_(list(platforms)),
                    User.links.any(AccountLink.platform.in_(list(platforms))),
                )
            )
        statement = statement.order_by(Event.remind_at.asc()).limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_all_for_user(self, user_id: int) -> list[Event]:
        statement = (
            select(Event)
            .where(Event.user_id == user_id, Event.status != EventStatus.CANCELLED)
            .order_by(Event.starts_at.is_(None), Event.starts_at.asc(), Event.id.asc())
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def mark_reminder_sent(self, event: Event, sent_at: datetime | None = None) -> Event:
        sent_moment = sent_at or utcnow()
        event.reminder_sent_at = to_db(sent_moment)
        if event.rrule and event.remind_at:
            from app.core.recurrence import next_recurrence
            from app.core.timeutils import from_db
            curr_remind = from_db(event.remind_at)
            next_dt = next_recurrence(event.rrule, curr_remind, sent_moment)
            if next_dt:
                if event.starts_at:
                    delta = from_db(event.starts_at) - curr_remind
                    event.starts_at = to_db(next_dt + delta)
                event.remind_at = to_db(next_dt)
                event.reminder_sent_at = None
        await self.session.commit()
        return event
