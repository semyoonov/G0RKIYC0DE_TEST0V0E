import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.db.models import Event, User  # noqa: F401  (register mappers)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite://",
        cache_enabled=False,
        auto_create_tables=False,
        gigachat_credentials="",
        sber_tts_credentials="",
        telegram_bot_token="",
        max_bot_token="",
        timezone="Europe/Moscow",
    )


@pytest.fixture
async def engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(engine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def session(session_factory):
    async with session_factory() as session:
        yield session
