import time

import httpx
import pytest

from app.ai.tts.sber_tts import SberTextToSpeech
from app.core.config import Settings
from app.core.exceptions import ConfigurationError, SpeechSynthesisError

AUTH_URL = "https://auth.example.test/api/v2/oauth"
SYNTH_URL = "https://tts.example.test/rest/v1/text:synthesize"
CREDENTIALS = "client-id:client-secret"
AUDIO = b"OPUS-BYTES"


class _Backend:
    def __init__(self, synth_status: int = 200, synth_body: bytes = AUDIO) -> None:
        self.requests: list[httpx.Request] = []
        self._synth_status = synth_status
        self._synth_body = synth_body

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/v2/oauth":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token",
                    "expires_at": int((time.time() + 1800) * 1000),
                },
            )
        return httpx.Response(self._synth_status, content=self._synth_body)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "sber_tts_credentials": CREDENTIALS,
        "sber_tts_auth_url": AUTH_URL,
        "sber_tts_url": SYNTH_URL,
        "sber_tts_voice": "Nec_24000",
        "sber_tts_format": "opus",
    }
    values.update(overrides)
    return Settings(**values)


def _synth_requests(backend: _Backend) -> list[httpx.Request]:
    return [request for request in backend.requests if request.url.path.endswith(":synthesize")]


async def test_synthesize_sends_token_format_voice_and_text() -> None:
    backend = _Backend()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as client:
        tts = SberTextToSpeech(_settings(), client=client)

        audio = await tts.synthesize("напомни позвонить маме", audio_format="opus", voice="Bys_24000")
        await tts.close()

    assert audio == AUDIO
    assert len(backend.requests) == 2
    token_request, synth_request = backend.requests
    assert token_request.url.path == "/api/v2/oauth"
    assert token_request.headers["Authorization"] == f"Basic {CREDENTIALS}"

    assert synth_request.headers["Authorization"] == "Bearer access-token"
    assert synth_request.headers["Content-Type"] == "application/text"
    assert synth_request.url.params["format"] == "opus"
    assert synth_request.url.params["voice"] == "Bys_24000"
    assert synth_request.content.decode("utf-8") == "напомни позвонить маме"


async def test_synthesize_uses_settings_defaults_and_maps_unknown_format() -> None:
    backend = _Backend()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as client:
        tts = SberTextToSpeech(_settings(), client=client)

        await tts.synthesize("привет", audio_format="amr")

    synth_request = _synth_requests(backend)[-1]
    assert synth_request.url.params["format"] == "opus"
    assert synth_request.url.params["voice"] == "Nec_24000"


async def test_synthesize_truncates_long_text() -> None:
    backend = _Backend()
    long_text = "Очень длинное предложение для проверки обрезки. " * 200
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as client:
        tts = SberTextToSpeech(_settings(), client=client)

        await tts.synthesize(long_text)

    body = _synth_requests(backend)[-1].content.decode("utf-8")
    assert 0 < len(body) <= 4000
    assert long_text.startswith(body)


async def test_non_200_synthesis_raises_speech_synthesis_error() -> None:
    backend = _Backend(synth_status=401, synth_body=b"Unauthorized")
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as client:
        tts = SberTextToSpeech(_settings(), client=client)

        with pytest.raises(SpeechSynthesisError, match="401"):
            await tts.synthesize("привет")


async def test_empty_audio_response_raises_speech_synthesis_error() -> None:
    backend = _Backend(synth_body=b"")
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as client:
        tts = SberTextToSpeech(_settings(), client=client)

        with pytest.raises(SpeechSynthesisError):
            await tts.synthesize("привет")


async def test_whitespace_text_returns_empty_bytes_without_http_call() -> None:
    backend = _Backend()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as client:
        tts = SberTextToSpeech(_settings(), client=client)

        assert await tts.synthesize("   \n\t ") == b""
        assert await tts.synthesize("") == b""

    assert backend.requests == []


async def test_missing_credentials_raises_configuration_error() -> None:
    backend = _Backend()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as client:
        tts = SberTextToSpeech(_settings(sber_tts_credentials=""), client=client)

        with pytest.raises(ConfigurationError):
            await tts.synthesize("привет")

    assert backend.requests == []


async def test_close_is_idempotent_for_owned_client() -> None:
    tts = SberTextToSpeech(_settings())

    await tts.close()
    await tts.close()


async def test_close_does_not_close_injected_client() -> None:
    backend = _Backend()
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as client:
        tts = SberTextToSpeech(_settings(), client=client)

        await tts.close()
        response = await client.get("https://tts.example.test/ping")

    assert response.status_code == 200
