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
from test_auth_service import auth_settings

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
    ) -> AssistantResponse:
        self.text_calls.append((platform, external_user_id, text))
        return AssistantResponse(text=f"Ответ: {text}", events=[make_event(1)])

    async def list_events(self, platform: Platform, external_user_id: str, period: Period) -> list[EventRead]:
        self.list_calls.append((platform, external_user_id, period))
        return [make_event(2)]


def build_app(session_factory, settings: Settings | None = None) -> tuple[Any, FakeAssistant]:
    assistant = FakeAssistant()
    auth = AuthService(session_factory, settings or auth_settings())
    app = create_app(assistant, settings or auth_settings(), auth=auth)
    return app, assistant


async def request(app: Any, method: str, url: str, **kwargs: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


async def test_web_session_endpoint_returns_token(session_factory) -> None:
    app, _ = build_app(session_factory)

    response = await request(
        app,
        "POST",
        "/api/auth/session",
        json={"platform": "web", "client_id": "web-browser-7"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["identity"]["platform"] == "web"
    assert body["identity"]["external_id"] == "web-browser-7"
    assert body["token"]
    assert body["mini_apps"]["telegram"].startswith("https://t.me/")
    assert body["user"]["id"] > 0


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
        json={"text": "Что у меня сегодня?", "client_id": "ignored"},
        headers={"Authorization": f"Bearer {session['token']}"},
    )

    assert response.status_code == 200
    assert assistant.text_calls == [(Platform.TELEGRAM, "42", "Что у меня сегодня?")]


async def test_chat_without_token_keeps_client_id(session_factory) -> None:
    app, assistant = build_app(session_factory)

    response = await request(app, "POST", "/api/chat", json={"text": "Привет", "client_id": "web-legacy"})

    assert response.status_code == 200
    assert assistant.text_calls == [(Platform.WEB, "web-legacy", "Привет")]


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


async def test_link_code_flow_over_http(session_factory) -> None:
    app, _ = build_app(session_factory)
    web = (
        await request(app, "POST", "/api/auth/session", json={"platform": "web", "client_id": "web-http"})
    ).json()
    headers = {"Authorization": f"Bearer {web['token']}"}

    issued = (await request(app, "POST", "/api/auth/code", headers=headers)).json()
    assert len(issued["code"]) == 6

    linked = (
        await request(
            app,
            "POST",
            "/api/auth/link",
            json={"code": issued["code"].lower()},
            headers=headers,
        )
    ).json()
    assert linked["link_redeemed"] is True
    assert linked["identity"]["external_id"] == "web-http"

    me = (await request(app, "GET", "/api/auth/me", headers=headers)).json()
    assert me["user"]["id"] == linked["user"]["id"]


async def test_link_rejects_bad_code(session_factory) -> None:
    app, _ = build_app(session_factory)
    web = (await request(app, "POST", "/api/auth/session", json={"platform": "web"})).json()
    headers = {"Authorization": f"Bearer {web['token']}"}

    response = await request(app, "POST", "/api/auth/link", json={"code": "AAAAAA"}, headers=headers)

    assert response.status_code == 400


async def test_anonymous_cannot_request_a_code(session_factory) -> None:
    app, _ = build_app(session_factory)

    response = await request(app, "POST", "/api/auth/code")

    assert response.status_code == 401


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
    assert f"https://vk.com/app{VK_APP_ID}" in body["mini_apps"].values()
