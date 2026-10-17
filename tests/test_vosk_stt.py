import io
import wave
from pathlib import Path

import pytest

from app.ai.stt.vosk_stt import VoskSpeechRecognizer
from app.core.exceptions import ConfigurationError, TranscriptionError

REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPO_ROOT / "models" / "vosk-model-small-ru-0.22"


def _silent_wav(
    *,
    channels: int = 1,
    sample_width: int = 2,
    frame_rate: int = 16000,
    seconds: float = 0.5,
) -> bytes:
    frames = int(frame_rate * seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(frame_rate)
        wav.writeframes(b"\x00" * frames * channels * sample_width)
    return buffer.getvalue()


async def test_rejects_non_wav_input(tmp_path: Path) -> None:
    recognizer = VoskSpeechRecognizer(str(tmp_path / "missing-model"))

    with pytest.raises(TranscriptionError, match="WAV"):
        await recognizer.transcribe(b"ID3\x03\x00 definitely not a wav file")


@pytest.mark.parametrize(
    ("channels", "sample_width", "frame_rate"),
    [(2, 2, 16000), (1, 1, 16000), (1, 2, 8000), (1, 4, 16000)],
)
async def test_rejects_wrong_wav_layout(
    tmp_path: Path,
    channels: int,
    sample_width: int,
    frame_rate: int,
) -> None:
    recognizer = VoskSpeechRecognizer(str(tmp_path / "missing-model"))

    with pytest.raises(TranscriptionError, match="mono 16-bit"):
        await recognizer.transcribe(
            _silent_wav(channels=channels, sample_width=sample_width, frame_rate=frame_rate)
        )


async def test_missing_model_directory_raises_configuration_error(tmp_path: Path) -> None:
    missing = tmp_path / "vosk-model-small-ru-0.22"
    recognizer = VoskSpeechRecognizer(str(missing))

    assert recognizer.available is False
    with pytest.raises(ConfigurationError) as error:
        await recognizer.transcribe(_silent_wav())

    message = str(error.value)
    assert str(missing) in message
    assert "https://alphacephei.com/vosk/models" in message


async def test_configured_model_path_is_reported_in_error() -> None:
    recognizer = VoskSpeechRecognizer(str(MODEL_PATH))

    assert recognizer.available is MODEL_PATH.is_dir()
    if MODEL_PATH.is_dir():
        pytest.skip("model directory exists; missing-model branch is covered above")
    with pytest.raises(ConfigurationError) as error:
        await recognizer.transcribe(_silent_wav())

    assert str(MODEL_PATH) in str(error.value)


@pytest.mark.skipif(not MODEL_PATH.is_dir(), reason="Vosk model is not downloaded")
async def test_real_model_returns_no_speech_for_silence() -> None:
    recognizer = VoskSpeechRecognizer(str(MODEL_PATH))

    with pytest.raises(TranscriptionError, match="речь не распознана"):
        await recognizer.transcribe(_silent_wav(seconds=0.3))
