from __future__ import annotations

import time

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models.event import Event
from app.domain.enums import EventStatus, EventType, Platform
from app.domain.identity import Identity
from app.repositories.account_repository import AccountRepository, LinkCodeError
from app.repositories.user_repository import UserRepository
from app.services.auth.service import AuthService
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
        "link_code_ttl_seconds": 900,
        "web_public_url": "https://assistant.test",
        "timezone": "Europe/Moscow",
        "email_code_secret": "test-email-secret",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


class FakeEmailSender:
    configured = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_login_code(self, email: str, code: str) -> None:
        self.sent.append((email, code))


@pytest.fixture
def auth(session_factory) -> AuthService:
    return AuthService(session_factory, auth_settings(), email_sender=FakeEmailSender())


async def create_web_session(auth: AuthService, email: str):
    await auth.request_email_code(email)
    sender = auth._email_sender  # noqa: SLF001 - fake sender exposes the code for tests
    code = sender.sent[-1][1]
    return await auth.verify_email_code(email, code)


async def test_web_session_requires_email_verification(auth: AuthService) -> None:
    from app.services.auth.launch import LaunchError

    with pytest.raises(LaunchError):
        await auth.open_session(Platform.WEB)


async def test_web_email_code_creates_a_verified_session(auth: AuthService) -> None:
    session = await create_web_session(auth, "Person@Example.com")

    assert session.identity.platform is Platform.WEB
    assert session.identity.external_id.startswith("email-")
    restored = await auth.account(session.token)
    assert restored.user_id == session.user_id


async def test_email_login_links_a_bot_account_and_preserves_its_id(auth: AuthService) -> None:
    telegram = await auth.open_session(Platform.TELEGRAM, telegram_init_data())
    identity = Identity(Platform.TELEGRAM, "42")
    await auth.request_email_code("same@example.com", identity)
    sender = auth._email_sender  # noqa: SLF001 - fake sender exposes the code for tests
    email_session = await auth.verify_email_code("same@example.com", sender.sent[-1][1], identity)

    browser_session = await create_web_session(auth, "same@example.com")

    assert email_session.user_id == telegram.user_id
    assert browser_session.user_id == telegram.user_id


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


async def test_start_param_links_web_account_to_telegram(auth: AuthService, session_factory) -> None:
    web_session = await create_web_session(auth, "before-link@example.com")
    async with session_factory() as session:
        session.add(
            Event(
                user_id=web_session.user_id,
                type=EventType.TASK,
                title="Позвонить в банк",
                status=EventStatus.PENDING,
                source=Platform.WEB,
            )
        )
        await session.commit()

    issued = await auth.issue_link_code(web_session.identity)

    telegram_session = await auth.open_session(
        Platform.TELEGRAM,
        telegram_init_data(start_param=issued["code"]),
    )

    assert telegram_session.link_redeemed is True
    assert telegram_session.user_id == web_session.user_id
    platforms = {identity.platform for identity in telegram_session.linked}
    assert {Platform.WEB, Platform.TELEGRAM} <= platforms

    restored = await auth.account(web_session.token)
    assert restored.user_id == telegram_session.user_id

    async with session_factory() as session:
        rows = (await session.execute(select(Event).where(Event.user_id == telegram_session.user_id))).scalars()
        assert [row.title for row in rows.all()] == ["Позвонить в банк"]


async def test_redeem_moves_history_to_the_bot_account(auth: AuthService, session_factory) -> None:
    telegram_session = await auth.open_session(Platform.TELEGRAM, telegram_init_data())
    issued = await auth.issue_link_code(Identity(Platform.TELEGRAM, "42"))
    web_session = await create_web_session(auth, "web-guest@example.com")
    async with session_factory() as session:
        session.add(
            Event(
                user_id=web_session.user_id,
                type=EventType.REMINDER,
                title="Купить билеты",
                status=EventStatus.PENDING,
                source=Platform.WEB,
            )
        )
        await session.commit()

    linked = await auth.redeem(web_session.identity, issued["code"])

    assert linked.user_id == telegram_session.user_id
    async with session_factory() as session:
        rows = (await session.execute(select(Event).where(Event.user_id == telegram_session.user_id))).scalars()
        assert [row.title for row in rows.all()] == ["Купить билеты"]
        leftover = (await session.execute(select(Event).where(Event.user_id == web_session.user_id))).scalars()
        assert leftover.all() == []


async def test_linked_identity_resolves_through_the_user_repository(
    auth: AuthService,
    session_factory,
) -> None:
    owner = await auth.open_session(Platform.TELEGRAM, telegram_init_data())
    issued = await auth.issue_link_code(Identity(Platform.TELEGRAM, "42"))
    guest = await create_web_session(auth, "web-linked@example.com")
    await auth.redeem(guest.identity, issued["code"])

    async with session_factory() as session:
        repository = UserRepository(session)
        resolved = await repository.get_or_create(Platform.WEB, guest.identity.external_id)
        stranger = await repository.get_or_create(Platform.WEB, "web-unlinked")

    assert resolved.id == owner.user_id
    assert resolved.id != guest.user_id
    assert stranger.id != owner.user_id


async def test_redeem_rejects_used_and_unknown_codes(auth: AuthService) -> None:
    issued = await auth.issue_link_code(Identity(Platform.WEB, "web-once"))
    await auth.redeem(Identity(Platform.TELEGRAM, "100"), issued["code"])

    with pytest.raises(LinkCodeError):
        await auth.redeem(Identity(Platform.TELEGRAM, "101"), issued["code"])
    with pytest.raises(LinkCodeError):
        await auth.redeem(Identity(Platform.TELEGRAM, "102"), "ZZZZZZ")


async def test_redeem_rejects_expired_code(auth: AuthService) -> None:
    issued = await auth.issue_link_code(Identity(Platform.WEB, "web-expired"))
    async with auth._session_factory() as session:  # noqa: SLF001 - the fixture builds the repository directly
        repository = AccountRepository(session)
        row = await repository.find_code(issued["code"])
        assert row is not None
        row.expires_at = row.expires_at.replace(year=2000)
        await session.commit()

    with pytest.raises(LinkCodeError):
        await auth.redeem(Identity(Platform.TELEGRAM, "103"), issued["code"])


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


async def test_issue_code_reports_mini_app_links(auth: AuthService) -> None:
    issued = await auth.issue_link_code(Identity(Platform.TELEGRAM, "42"))

    assert issued["mini_apps"]["telegram"].startswith("https://t.me/hackathon_helperbot?start=")
    assert issued["mini_apps"]["max"].startswith("https://max.ru/helper_max?startapp=")
    assert issued["mini_apps"]["vk"].startswith(f"https://vk.com/app{VK_APP_ID}#")
    assert issued["web_link"].startswith("https://assistant.test/?link=")
    assert issued["expires_in"] == 900
    assert int(time.time()) > 0


async def test_start_param_links_web_account_to_vk(auth: AuthService, session_factory) -> None:
    web_session = await create_web_session(auth, "vk-link-test@example.com")
    async with session_factory() as session:
        session.add(
            Event(
                user_id=web_session.user_id,
                type=EventType.TASK,
                title="Задача из веба для ВК",
                status=EventStatus.PENDING,
                source=Platform.WEB,
            )
        )
        await session.commit()

    issued = await auth.issue_link_code(web_session.identity)
    code = issued["code"]

    vk_session = await auth.open_session(
        Platform.VK,
        vk_launch_params(start_param=code, urlsafe=True),
    )

    assert vk_session.link_redeemed is True
    assert vk_session.user_id == web_session.user_id
    platforms = {identity.platform for identity in vk_session.linked}
    assert {Platform.WEB, Platform.VK} <= platforms

    async with session_factory() as session:
        rows = (await session.execute(select(Event).where(Event.user_id == vk_session.user_id))).scalars()
        assert [row.title for row in rows.all()] == ["Задача из веба для ВК"]


async def test_start_param_links_web_account_to_max(auth: AuthService, session_factory) -> None:
    web_session = await create_web_session(auth, "max-link-test@example.com")
    async with session_factory() as session:
        session.add(
            Event(
                user_id=web_session.user_id,
                type=EventType.TASK,
                title="Задача из веба для MAX",
                status=EventStatus.PENDING,
                source=Platform.WEB,
            )
        )
        await session.commit()

    issued = await auth.issue_link_code(web_session.identity)
    code = issued["code"]

    max_session = await auth.open_session(
        Platform.MAX,
        max_init_data(start_param=code),
    )

    assert max_session.link_redeemed is True
    assert max_session.user_id == web_session.user_id
    platforms = {identity.platform for identity in max_session.linked}
    assert {Platform.WEB, Platform.MAX} <= platforms

    async with session_factory() as session:
        rows = (await session.execute(select(Event).where(Event.user_id == max_session.user_id))).scalars()
        assert [row.title for row in rows.all()] == ["Задача из веба для MAX"]

