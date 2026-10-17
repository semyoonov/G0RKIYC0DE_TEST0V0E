import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logger import get_logger
from app.db.models.event import Event
from app.db.models.user import User
from app.domain.enums import Platform
from app.repositories.event_repository import EventRepository

log = get_logger(__name__)


class Notifier(Protocol):
    platform: Platform

    async def __call__(self, user: User, event: Event) -> None: ...


class ReminderService:
    """Polls due reminders and delivers them through registered interface notifiers."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        poll_interval_seconds: int = 30,
        lookahead_seconds: int = 60,
    ) -> None:
        self._session_factory = session_factory
        self._poll_interval_seconds = poll_interval_seconds
        self._lookahead_seconds = lookahead_seconds
        self._notifiers: dict[Platform, Callable[[User, Event], Awaitable[None]]] = {}
        self._task: asyncio.Task[None] | None = None

    def register_notifier(self, platform: Platform, notifier: Callable[[User, Event], Awaitable[None]]) -> None:
        self._notifiers[platform] = notifier

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop(), name="reminder-service")
        log.info("reminder service started, interval=%ss", self._poll_interval_seconds)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_once(self) -> int:
        """Deliver all reminders that are due now; returns the delivered count."""
        if not self._notifiers:
            return 0
        async with self._session_factory() as session:
            repository = EventRepository(session)
            due = await repository.due_reminders(
                lookahead_seconds=self._lookahead_seconds,
                platforms=list(self._notifiers),
            )
            # Release the connection before notifier HTTP calls.
            await session.commit()
            delivered = 0
            for event in due:
                user = event.user
                notifier = self._notifiers.get(user.platform)
                if notifier is None:
                    continue
                try:
                    await notifier(user, event)
                except Exception:  # noqa: BLE001 - one failing channel must not stop the loop
                    log.exception("reminder %s delivery to %s failed", event.id, user.platform)
                    continue
                await repository.mark_reminder_sent(event)
                delivered += 1
            return delivered

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep the scheduler alive
                log.exception("reminder cycle failed")
            await asyncio.sleep(self._poll_interval_seconds)
