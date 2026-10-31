import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import NotFoundError
from app.domain.enums import Period, Platform
from app.domain.identity import Identity
from app.domain.models import AssistantResponse
from app.interfaces.web import routes as routes_module
from app.interfaces.web.app import create_app



class FakeAssistant:
    async def handle_text(self, platform, external_user_id, text, *, speak=False, audio_format=None):
        return AssistantResponse(text="ответ")

    async def handle_voice(self, platform, external_user_id, audio, *, source_format=None, speak=True, audio_format=None):
        return AssistantResponse(text="ответ")

    async def list_events(self, platform, external_user_id, period=Period.WEEK):
        return []

    async def set_event_status(self, platform, external_user_id, event_id, status):
        raise NotFoundError(f"event {event_id} not found")


class FakeAuth:
    def __init__(self, settings):
        self.settings = settings

    async def account(self, token: str):
        class Account:
            identity = Identity(platform=Platform.WEB, external_id="web-demo")
        return Account()


@pytest.fixture
async def client(settings):
    app = create_app(FakeAssistant(), settings, auth=FakeAuth(settings))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer dummy"},
    ) as http_client:
        yield http_client


async def test_audio_upload_is_capped(client, monkeypatch):
    monkeypatch.setattr(routes_module, "MAX_AUDIO_BYTES", 8)

    response = await client.post(
        "/api/voice",
        files={"audio": ("voice.ogg", b"0123456789", "audio/ogg")},
        data={"client_id": "web-demo"},
    )

    assert response.status_code == 413


async def test_invalid_period_is_validated(client):
    response = await client.get("/api/events", params={"period": "invalid_period"})

    assert response.status_code == 422


async def test_unknown_event_returns_404(client):
    response = await client.post("/api/events/999/complete", params={"client_id": "web-demo"})

    assert response.status_code == 404
