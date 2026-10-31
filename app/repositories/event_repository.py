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


def _token_patterns(token: str) -> list[str]:
    lowered = token.lower()
    variants = [lowered, lowered.capitalize()]
    for cut in (1, 2, 3):
        if len(lowered) - cut >= 4:
            stem = lowered[:-cut]
            variants.extend([stem, stem.capitalize()])
    return [f"%{variant}%" for variant in dict.fromkeys(variants)]


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
        tokens = [token for token in _WORD_RE.findall(query.lower()) if token not in _SEARCH_STOPWORDS]
        if not tokens:
            return []

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

        # 1. Conjunction (all search terms match)
        statement = (
            select(Event)
            .where(*base_filter, and_(*token_conditions))
            .order_by(
                Event.starts_at.is_(None),
                Event.starts_at.desc(),
                Event.created_at.desc(),
            )
            .limit(limit)
        )
        result = await self.session.execute(statement)
        matches = list(result.scalars().all())
        if matches:
            return matches

        # 2. Fallback when extra words (e.g. weekdays, recurrence) are in the query
        if len(tokens) > 1:
            statement = (
                select(Event)
                .where(*base_filter, or_(*token_conditions))
                .limit(max(limit * 3, 20))
            )
            result = await self.session.execute(statement)
            candidates = list(result.scalars().all())
            if candidates:
                query_lower = query.lower().strip()

                def rank_key(event: Event) -> tuple[int, int, bool, datetime]:
                    t_lower = (event.title or "").lower().strip()
                    title_match = 2 if (t_lower and (t_lower in query_lower or query_lower in t_lower)) else 0
                    token_hits = sum(1 for t in tokens if t in t_lower)
                    is_pending = event.status == EventStatus.PENDING
                    created = event.created_at or datetime.min
                    return (title_match, token_hits, is_pending, created)

                candidates.sort(key=rank_key, reverse=True)
                return candidates[:limit]

        return []

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
