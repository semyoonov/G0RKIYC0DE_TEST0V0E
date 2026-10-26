import io
import shutil
import wave

import pytest

from app.ai.tts.cloud_tts import CloudTextToSpeech
from app.core.config import Settings
from app.core.exceptions import ConfigurationError, SpeechSynthesisError

PCM = b"\x01\x02" * 24000


def make_tts(settings: Settings, pcm: bytes = PCM) -> tuple[CloudTextToSpeech, list[tuple[str, str]]]:
    calls: list[tuple[str, str]] = []

    async def fetch(text: str, voice: str) -> bytes:
        calls.append((text, voice))
        return pcm

    return CloudTextToSpeech(settings.model_copy(update={"cloud_tts_api_key": "key"}), fetch=fetch), calls


def test_synthesize_returns_wav_without_ffmpeg(settings: Settings) -> None:
    tts, calls = make_tts(settings)

    async def scenario() -> bytes:
        return await tts.synthesize("  Встреча завтра в 10.  ", audio_format="wav")

    import asyncio

    audio = asyncio.run(scenario())

    assert calls == [("Встреча завтра в 10.", settings.cloud_tts_voice)]
    with wave.open(io.BytesIO(audio), "rb") as stream:
        assert stream.getframerate() == 24000
        assert stream.getnchannels() == 1
        assert stream.getsampwidth() == 2
        assert stream.getnframes() == 24000


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_synthesize_wraps_audio_in_opus(settings: Settings) -> None:
    import asyncio

    tts, _ = make_tts(settings)
    audio = asyncio.run(tts.synthesize("Готово.", audio_format="opus"))

    assert audio[:4] == b"OggS"
    assert len(audio) > 1000


def test_empty_model_audio_is_an_error(settings: Settings) -> None:
    import asyncio

    tts, _ = make_tts(settings, pcm=b"")
    with pytest.raises(SpeechSynthesisError):
        asyncio.run(tts.synthesize("Готово.", audio_format="wav"))


def test_missing_key_is_a_configuration_error(settings: Settings) -> None:
    import asyncio

    tts = CloudTextToSpeech(settings.model_copy(update={"cloud_tts_api_key": ""}))
    with pytest.raises(ConfigurationError):
        asyncio.run(tts.synthesize("Готово.", audio_format="wav"))


def test_transport_failure_becomes_speech_synthesis_error(settings: Settings) -> None:
    import asyncio

    async def fetch(text: str, voice: str) -> bytes:
        raise SpeechSynthesisError("Cloud.ru TTS недоступен")

    tts = CloudTextToSpeech(settings.model_copy(update={"cloud_tts_api_key": "key"}), fetch=fetch)
    with pytest.raises(SpeechSynthesisError):
        asyncio.run(tts.synthesize("Готово.", audio_format="wav"))


def test_blank_text_returns_no_audio(settings: Settings) -> None:
    import asyncio

    tts, calls = make_tts(settings)
    assert asyncio.run(tts.synthesize("   ")) == b""
    assert calls == []
