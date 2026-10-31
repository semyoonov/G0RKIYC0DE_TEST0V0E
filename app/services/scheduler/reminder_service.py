import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logger import get_logger
from app.db.models.event import Event
from app.db.models.user import User
from app.domain.enums import Platform
from app.repositories.event_repository import EventRepository

log = get_logger(__name__)


class ReminderService:
    """Опрашивает наступившие напоминания и отдаёт их нотификаторам интерфейсов."""

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
        """Отправляет все наступившие напоминания; возвращает число отправленных."""
        if not self._notifiers:
            return 0
        async with self._session_factory() as session:
            repository = EventRepository(session)
            due = await repository.due_reminders(
                lookahead_seconds=self._lookahead_seconds,
                platforms=list(self._notifiers),
            )
            # Освобождаем соединение до HTTP-вызовов нотификаторов.
            await session.commit()
            delivered = 0
            for event in due:
                user = event.user
                recipients: list[User] = []
                if user.platform in self._notifiers:
                    recipients.append(user)
                for link in getattr(user, "links", []):
                    if link.platform in self._notifiers:
                        linked_user = User(
                            id=user.id,
                            platform=link.platform,
                            external_id=link.external_id,
                            username=user.username,
                            timezone=user.timezone,
                        )
                        recipients.append(linked_user)

                if not recipients:
                    continue

                sent_any = False
                for recipient in recipients:
                    notifier = self._notifiers.get(recipient.platform)
                    if notifier is None:
                        continue
                    try:
                        await notifier(recipient, event)
                        sent_any = True
                    except Exception:  # noqa: BLE001 - one failing channel must not stop the loop
                        log.exception("reminder %s delivery to %s:%s failed", event.id, recipient.platform, recipient.external_id)

                if sent_any:
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
