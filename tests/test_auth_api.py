from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.domain.enums import EventStatus, EventType, Period, Platform
from app.domain.models import AssistantResponse, EventRead
from app.interfaces.web.app import create_app
from app.services.auth.service import AuthService
from test_auth_launch import (
    MAX_TOKEN,
    TELEGRAM_TOKEN,
    VK_APP_ID,
    VK_SECRET,
    max_init_data,
    telegram_init_data,
    vk_launch_params,
)
from test_auth_service import PASSWORD, auth_settings

FIXED_TIME = datetime(2025, 5, 20, 9, 30, tzinfo=timezone.utc)


def make_event(event_id: int = 1) -> EventRead:
    return EventRead(
        id=event_id,
        user_id=1,
        type=EventType.MEETING,
        title="Встреча с Анной",
        description=None,
        starts_at=FIXED_TIME,
        remind_at=None,
        status=EventStatus.PENDING,
        source=Platform.WEB,
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )


class FakeAssistant:
    def __init__(self) -> None:
        self.text_calls: list[tuple[Platform, str, str]] = []
        self.list_calls: list[tuple[Platform, str, Period]] = []

    async def handle_text(
        self,
        platform: Platform,
        external_user_id: str,
        text: str,
        *,
        speak: bool = False,
        closing: bool = False,
        voice: str | None = None,
    ) -> AssistantResponse:
        self.text_calls.append((platform, external_user_id, text))
        return AssistantResponse(text=f"Ответ: {text}", events=[make_event(1)])

    async def list_events(self, platform: Platform, external_user_id: str, period: Period) -> list[EventRead]:
        self.list_calls.append((platform, external_user_id, period))
        return [make_event(2)]


def build_app(session_factory, settings: Settings | None = None) -> tuple[Any, FakeAssistant]:
    assistant = FakeAssistant()
    active_settings = settings or auth_settings()
    auth = AuthService(session_factory, active_settings)
    app = create_app(assistant, active_settings, auth=auth)
    return app, assistant


async def create_web_session(app: Any, email: str) -> dict[str, Any]:
    response = await request(
        app,
        "POST",
        "/api/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def request(app: Any, method: str, url: str, **kwargs: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


async def test_web_session_endpoint_rejects_anonymous_login(session_factory) -> None:
    app, _ = build_app(session_factory)

    response = await request(
        app,
        "POST",
        "/api/auth/session",
        json={"platform": "web"},
    )

    assert response.status_code == 401


async def test_telegram_session_and_chat_use_token_identity(session_factory) -> None:
    app, assistant = build_app(session_factory)

    session = (
        await request(
            app,
            "POST",
            "/api/auth/session",
            json={"platform": "telegram", "payload": telegram_init_data()},
        )
    ).json()

    response = await request(
        app,
        "POST",
        "/api/chat",
        json={"text": "Что у меня сегодня?"},
        headers={"Authorization": f"Bearer {session['token']}"},
    )

    assert response.status_code == 200
    assert assistant.text_calls == [(Platform.TELEGRAM, "42", "Что у меня сегодня?")]


async def test_chat_without_token_is_rejected(session_factory) -> None:
    app, assistant = build_app(session_factory)

    response = await request(app, "POST", "/api/chat", json={"text": "Привет"})

    assert response.status_code == 401
    assert assistant.text_calls == []


async def test_web_event_routes_require_a_verified_session(session_factory) -> None:
    app, _ = build_app(session_factory)

    events = await request(app, "GET", "/api/events")
    completion = await request(app, "POST", "/api/events/1/complete")
    export = await request(app, "GET", "/api/calendar/export.ics")

    assert events.status_code == 401
    assert completion.status_code == 401
    assert export.status_code == 401


async def test_invalid_launch_data_is_rejected(session_factory) -> None:
    app, _ = build_app(session_factory)

    response = await request(
        app,
        "POST",
        "/api/auth/session",
        json={"platform": "telegram", "payload": "auth_date=1&hash=deadbeef"},
    )

    assert response.status_code == 401


async def test_unconfigured_platform_is_unavailable(session_factory) -> None:
    settings = auth_settings(telegram_bot_token="")
    app, _ = build_app(session_factory, settings)

    response = await request(
        app,
        "POST",
        "/api/auth/session",
        json={"platform": "telegram", "payload": telegram_init_data()},
    )

    assert response.status_code == 503


async def test_max_and_vk_sessions_over_http(session_factory) -> None:
    app, _ = build_app(session_factory)

    max_response = await request(
        app,
        "POST",
        "/api/auth/session",
        json={"platform": "max", "payload": max_init_data()},
    )
    vk_response = await request(
        app,
        "POST",
        "/api/auth/session",
        json={"platform": "vk", "payload": vk_launch_params()},
    )

    assert max_response.status_code == 200
    assert max_response.json()["identity"]["platform"] == "max"
    assert vk_response.status_code == 200
    assert vk_response.json()["identity"]["external_id"] == "555"


@pytest.mark.parametrize(
    ("platform", "token_name"),
    [("telegram", TELEGRAM_TOKEN), ("max", MAX_TOKEN), ("vk", VK_SECRET)],
)
async def test_meta_exposes_configured_platforms(session_factory, platform: str, token_name: str) -> None:
    app, _ = build_app(session_factory)

    body = (await request(app, "GET", "/api/meta")).json()

    assert platform in body["platforms"]
    assert token_name
    assert body["mini_apps"]["vk"] == f"https://vk.com/app{VK_APP_ID}"


async def test_guest_endpoint_opens_a_working_account(session_factory) -> None:
    app, assistant = build_app(session_factory)

    guest = await request(app, "POST", "/api/auth/guest")

    assert guest.status_code == 200
    payload = guest.json()
    assert payload["email"] is None
    assert payload["has_password"] is False

    chat = await request(
        app,
        "POST",
        "/api/chat",
        json={"text": "Что у меня сегодня?"},
        headers={"Authorization": f"Bearer {payload['token']}"},
    )

    assert chat.status_code == 200
    assert assistant.text_calls[0][0] is Platform.WEB


async def test_register_then_login_opens_the_same_account(session_factory) -> None:
    app, _ = build_app(session_factory)

    registered = await create_web_session(app, "account@example.com")
    logged = await request(
        app,
        "POST",
        "/api/auth/login",
        json={"email": "account@example.com", "password": PASSWORD},
    )

    assert registered["email"] == "account@example.com"
    assert registered["has_password"] is True
    assert logged.status_code == 200
    assert logged.json()["user"]["id"] == registered["user"]["id"]


async def test_register_rejects_a_registered_email(session_factory) -> None:
    app, _ = build_app(session_factory)
    await create_web_session(app, "taken@example.com")

    response = await request(
        app,
        "POST",
        "/api/auth/register",
        json={"email": "taken@example.com", "password": PASSWORD},
    )

    assert response.status_code == 409


async def test_login_rejects_a_wrong_password(session_factory) -> None:
    app, _ = build_app(session_factory)
    await create_web_session(app, "strict@example.com")

    response = await request(
        app,
        "POST",
        "/api/auth/login",
        json={"email": "strict@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401


async def test_short_password_is_rejected(session_factory) -> None:
    app, _ = build_app(session_factory)

    response = await request(
        app,
        "POST",
        "/api/auth/register",
        json={"email": "short@example.com", "password": "short"},
    )

    assert response.status_code == 422


async def test_registering_from_a_guest_keeps_its_events(session_factory) -> None:
    app, assistant = build_app(session_factory)
    guest = (await request(app, "POST", "/api/auth/guest")).json()
    headers = {"Authorization": f"Bearer {guest['token']}"}

    registered = await request(
        app,
        "POST",
        "/api/auth/register",
        json={"email": "guest@example.com", "password": PASSWORD},
        headers=headers,
    )

    assert registered.status_code == 200
    assert registered.json()["user"]["id"] == guest["user"]["id"]
    assert registered.json()["email"] == "guest@example.com"
    assert assistant.text_calls == []


async def test_login_from_a_mini_app_links_the_platform_identity(session_factory) -> None:
    app, _ = build_app(session_factory)
    registered = await create_web_session(app, "linked@example.com")
    telegram = (
        await request(
            app,
            "POST",
            "/api/auth/session",
            json={"platform": "telegram", "payload": telegram_init_data()},
        )
    ).json()

    logged = await request(
        app,
        "POST",
        "/api/auth/login",
        json={"email": "linked@example.com", "password": PASSWORD},
        headers={"Authorization": f"Bearer {telegram['token']}"},
    )

    assert logged.status_code == 200
    payload = logged.json()
    assert payload["user"]["id"] == registered["user"]["id"]
    assert payload["identity"]["platform"] == "telegram"
    assert {"web", "telegram"} <= {item["platform"] for item in payload["linked"]}
