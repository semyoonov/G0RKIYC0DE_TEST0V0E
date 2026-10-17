import io
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from app.ai.stt.audio_converter import AudioConverter
from app.core.exceptions import TranscriptionError

FFMPEG = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg binary is not available")


def _encode(target: Path, *codec_args: str) -> bytes:
    subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            *codec_args,
            str(target),
        ],
        check=True,
    )
    return target.read_bytes()


@pytest.fixture(scope="module")
def wav_source(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    target = tmp_path_factory.mktemp("audio") / "source.wav"
    return _encode(target, "-ac", "2", "-ar", "44100")


@pytest.fixture(scope="module")
def webm_source(tmp_path_factory: pytest.TempPathFactory) -> bytes:
    target = tmp_path_factory.mktemp("audio") / "source.webm"
    return _encode(target, "-c:a", "libopus", "-b:a", "32k")


def _assert_16k_mono_wav(data: bytes) -> None:
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"
    with wave.open(io.BytesIO(data)) as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16000


async def test_converts_wav_to_16k_mono(wav_source: bytes) -> None:
    converter = AudioConverter(ffmpeg_binary=FFMPEG or "ffmpeg")

    converted = await converter.to_wav(wav_source, source_hint="wav")

    _assert_16k_mono_wav(converted)


async def test_converts_webm_opus_to_16k_mono(webm_source: bytes) -> None:
    converter = AudioConverter(ffmpeg_binary=FFMPEG or "ffmpeg")

    converted = await converter.to_wav(webm_source, source_hint="audio/webm")

    _assert_16k_mono_wav(converted)


async def test_converts_without_source_hint(webm_source: bytes) -> None:
    converter = AudioConverter(ffmpeg_binary=FFMPEG or "ffmpeg")

    converted = await converter.to_wav(webm_source)

    _assert_16k_mono_wav(converted)


async def test_probe_duration_returns_seconds(wav_source: bytes) -> None:
    converter = AudioConverter(ffmpeg_binary=FFMPEG or "ffmpeg")

    duration = await converter.probe_duration(wav_source)

    assert duration == pytest.approx(1.0, abs=0.1)


async def test_empty_input_is_rejected() -> None:
    converter = AudioConverter(ffmpeg_binary=FFMPEG or "ffmpeg")

    with pytest.raises(TranscriptionError):
        await converter.to_wav(b"")

    with pytest.raises(TranscriptionError):
        await converter.probe_duration(b"")


async def test_corrupt_audio_is_rejected() -> None:
    converter = AudioConverter(ffmpeg_binary=FFMPEG or "ffmpeg")

    with pytest.raises(TranscriptionError):
        await converter.to_wav(b"this is definitely not an audio file")


async def test_duration_limit_is_enforced(wav_source: bytes) -> None:
    converter = AudioConverter(
        ffmpeg_binary=FFMPEG or "ffmpeg",
        max_duration_seconds=0,
    )

    with pytest.raises(TranscriptionError):
        await converter.to_wav(wav_source)


async def test_missing_ffmpeg_binary_raises_configuration_error(wav_source: bytes) -> None:
    converter = AudioConverter(ffmpeg_binary="/nonexistent/ffmpeg-binary")

    with pytest.raises(Exception) as error:
        await converter.to_wav(wav_source)

    assert type(error.value).__name__ == "ConfigurationError"
