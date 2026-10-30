from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.db.models import AccountLink, EmailChallenge, Event, LinkCode, User, UserEmail  # noqa: F401  (register mappers before create_all)

__all__ = ["AccountLink", "Database", "EmailChallenge", "Event", "LinkCode", "User", "UserEmail"]


class Database:
    def __init__(self, settings: Settings, **engine_kwargs: Any) -> None:
        self.settings = settings
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url,
            echo=settings.db_echo,
            pool_pre_ping=True,
            **engine_kwargs,
        )
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False, autoflush=False
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def create_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(self._ensure_columns)

    @staticmethod
    def _ensure_columns(sync_conn: Any) -> None:
        from sqlalchemy import inspect, text
        inspector = inspect(sync_conn)
        tables = inspector.get_table_names()
        if "events" in tables:
            columns = {col["name"] for col in inspector.get_columns("events")}
            if "rrule" not in columns:
                sync_conn.execute(text("ALTER TABLE events ADD COLUMN rrule VARCHAR(255)"))

    async def drop_all(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)

    async def dispose(self) -> None:
        await self.engine.dispose()
