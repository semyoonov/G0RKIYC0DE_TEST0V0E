from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.timeutils import to_db, utcnow
from app.db.models.user_email import UserEmail
from app.db.models.event import Event
from app.domain.enums import EventStatus, EventType, Platform
from app.domain.identity import Identity
from app.services.auth.service import AuthService, CredentialsError, EmailAuthError
from app.services.auth.tokens import SessionTokenError, SessionTokens
from test_auth_launch import (
    MAX_TOKEN,
    TELEGRAM_TOKEN,
    VK_APP_ID,
    VK_SECRET,
    max_init_data,
    telegram_init_data,
    vk_launch_params,
)


def auth_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "database_url": "sqlite+aiosqlite://",
        "cache_enabled": False,
        "auto_create_tables": False,
        "gigachat_credentials": "",
        "sber_tts_credentials": "",
        "telegram_bot_token": TELEGRAM_TOKEN,
        "max_bot_token": MAX_TOKEN,
        "vk_bot_token": "",
        "vk_mini_app_secret": VK_SECRET,
        "vk_mini_app_id": VK_APP_ID,
        "telegram_bot_username": "hackathon_helperbot",
        "max_bot_username": "helper_max",
        "session_secret": "test-session-secret",
        "session_ttl_seconds": 3600,
        "web_public_url": "https://assistant.test",
        "timezone": "Europe/Moscow",
        "demo_seed_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


PASSWORD = "correct-horse-9"


@pytest.fixture
def auth(session_factory) -> AuthService:
    return AuthService(session_factory, auth_settings())


async def create_web_session(auth: AuthService, email: str):
    return await auth.register(email, PASSWORD)


async def test_browser_sessions_start_as_guests_not_through_launch(auth: AuthService) -> None:
    from app.services.auth.launch import LaunchError

    with pytest.raises(LaunchError):
        await auth.open_session(Platform.WEB)

    session = await auth.open_guest_session()

    assert session.identity.platform is Platform.WEB
    assert session.identity.external_id.startswith("guest-")
    assert session.email is None
    restored = await auth.account(session.token)
    assert restored.user_id == session.user_id
    assert restored.email is None


async def test_registering_with_a_password_creates_a_web_login(auth: AuthService) -> None:
    session = await auth.register("Person@Example.com", PASSWORD)

    assert session.identity.platform is Platform.WEB
    assert session.identity.external_id.startswith("email-")
    assert session.email == "person@example.com"
    assert session.has_password is True
    restored = await auth.account(session.token)
    assert restored.user_id == session.user_id
    assert restored.email == "person@example.com"


async def test_registering_from_a_bot_keeps_the_bot_account(auth: AuthService) -> None:
    telegram = await auth.open_session(Platform.TELEGRAM, telegram_init_data())
    identity = Identity(Platform.TELEGRAM, "42")

    registered = await auth.register("same@example.com", PASSWORD, identity)
    browser = await auth.login("same@example.com", PASSWORD)

    assert registered.user_id == telegram.user_id
    assert registered.identity.platform is Platform.TELEGRAM
    assert browser.user_id == telegram.user_id


async def test_registering_an_existing_email_is_rejected(auth: AuthService) -> None:
    await auth.register("taken@example.com", PASSWORD)

    with pytest.raises(EmailAuthError):
        await auth.register("taken@example.com", PASSWORD)


async def test_login_rejects_a_wrong_password(auth: AuthService) -> None:
    await auth.register("wrong-pass@example.com", PASSWORD)

    with pytest.raises(CredentialsError):
        await auth.login("wrong-pass@example.com", "not-the-password")
    with pytest.raises(CredentialsError):
        await auth.login("unknown@example.com", PASSWORD)


async def test_login_from_a_mini_app_links_its_platform_to_the_email_account(
    auth: AuthService,
    session_factory,
) -> None:
    browser = await auth.register("cross@example.com", PASSWORD)
    telegram = await auth.open_session(Platform.TELEGRAM, telegram_init_data())
    async with session_factory() as session:
        session.add(
            Event(
                user_id=telegram.user_id,
                type=EventType.TASK,
                title="Задача из Telegram",
                status=EventStatus.PENDING,
                source=Platform.TELEGRAM,
            )
        )
        await session.commit()

    linked = await auth.login("cross@example.com", PASSWORD, Identity(Platform.TELEGRAM, "42"))

    assert linked.user_id == browser.user_id
    assert linked.identity.platform is Platform.TELEGRAM
    assert {Platform.TELEGRAM, Platform.WEB} <= {identity.platform for identity in linked.linked}
    async with session_factory() as session:
        rows = (await session.execute(select(Event).where(Event.user_id == browser.user_id))).scalars()
        assert [row.title for row in rows.all()] == ["Задача из Telegram"]


async def test_a_leftover_email_can_be_claimed_only_by_its_own_account(
    auth: AuthService,
    session_factory,
) -> None:
    guest = await auth.open_guest_session()
    async with session_factory() as session:
        session.add(
            UserEmail(
                user_id=guest.user_id,
                email_normalized="leftover@example.com",
                web_identity_id="email-leftover",
                claimed_at=to_db(utcnow()),
            )
        )
        await session.commit()

    with pytest.raises(EmailAuthError):
        await auth.register("leftover@example.com", PASSWORD, Identity(Platform.TELEGRAM, "42"))

    claimed = await auth.register("leftover@example.com", PASSWORD, guest.identity)
    assert claimed.user_id == guest.user_id
    assert claimed.has_password is True


async def test_guest_registration_keeps_guest_events(auth: AuthService, session_factory) -> None:
    guest = await auth.open_guest_session()
    async with session_factory() as session:
        session.add(
            Event(
                user_id=guest.user_id,
                type=EventType.TASK,
                title="Задача из гостевой сессии",
                status=EventStatus.PENDING,
                source=Platform.WEB,
            )
        )
        await session.commit()

    registered = await auth.register("guest-upgrade@example.com", PASSWORD, guest.identity)

    assert registered.user_id == guest.user_id
    assert registered.email == "guest-upgrade@example.com"
    async with session_factory() as session:
        rows = (await session.execute(select(Event).where(Event.user_id == guest.user_id))).scalars()
        assert [row.title for row in rows.all()] == ["Задача из гостевой сессии"]


async def test_telegram_session_uses_platform_identity(auth: AuthService) -> None:
    session = await auth.open_session(Platform.TELEGRAM, telegram_init_data())

    assert session.identity.platform is Platform.TELEGRAM
    assert session.identity.external_id == "42"
    assert session.user_id > 0


async def test_max_and_vk_sessions(auth: AuthService) -> None:
    max_session = await auth.open_session(Platform.MAX, max_init_data())
    vk_session = await auth.open_session(Platform.VK, vk_launch_params())

    assert max_session.identity.external_id == "77"
    assert vk_session.identity.external_id == "555"


async def test_vk_login_takes_the_name_from_the_service_token(monkeypatch, session_factory) -> None:
    async def fake_fetch(access_token: str, user_id: str) -> str | None:
        assert access_token == "vk-service-token"
        assert user_id == "555"
        return "Иван Петров"

    monkeypatch.setattr("app.services.auth.service.fetch_display_name", fake_fetch)
    service = AuthService(session_factory, auth_settings(vk_access_token="vk-service-token"))

    session = await service.open_session(Platform.VK, vk_launch_params())

    assert session.identity.display_name == "Иван Петров"


async def test_vk_login_survives_a_failed_profile_lookup(monkeypatch, session_factory) -> None:
    async def fake_fetch(access_token: str, user_id: str) -> str | None:
        return None

    monkeypatch.setattr("app.services.auth.service.fetch_display_name", fake_fetch)
    service = AuthService(session_factory, auth_settings(vk_access_token="vk-service-token"))

    session = await service.open_session(Platform.VK, vk_launch_params())

    assert session.identity.platform is Platform.VK
    assert session.identity.display_name is None


async def test_vk_profile_lookup_without_a_token_skips_the_network() -> None:
    from app.services.auth.vk_profile import fetch_display_name

    assert await fetch_display_name("", "555") is None


def test_session_tokens_reject_expired_and_forged() -> None:
    tokens = SessionTokens("secret", ttl_seconds=60)
    token = tokens.issue(Identity(Platform.TELEGRAM, "42"), now=1000)

    assert tokens.parse(token, now=1030).external_id == "42"
    with pytest.raises(SessionTokenError):
        tokens.parse(token, now=2000)
    with pytest.raises(SessionTokenError):
        tokens.parse(token[:-2] + "AA", now=1030)


def test_session_tokens_reject_foreign_secret() -> None:
    token = SessionTokens("one", ttl_seconds=60).issue(Identity(Platform.WEB, "client"))

    with pytest.raises(SessionTokenError):
        SessionTokens("two", ttl_seconds=60).parse(token)


async def test_open_session_rejects_bad_launch_data(auth: AuthService) -> None:
    from app.services.auth.launch import LaunchError

    with pytest.raises(LaunchError):
        await auth.open_session(Platform.TELEGRAM, "auth_date=1&hash=deadbeef")


async def test_mini_app_links_open_the_app_without_a_code(auth: AuthService) -> None:
    links = auth.settings.mini_app_links()

    assert links["telegram"] == "https://t.me/hackathon_helperbot"
    assert links["max"] == "https://max.ru/helper_max"
    assert links["vk"] == f"https://vk.com/app{VK_APP_ID}"
    assert links["web"] == "https://assistant.test/"
