from __future__ import annotations

import asyncio
import base64
import io
import wave
from collections.abc import Awaitable, Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.core.config import Settings
from app.core.exceptions import ConfigurationError, SpeechSynthesisError
from app.core.logger import get_logger

log = get_logger(__name__)

_MAX_TEXT_CHARS = 4000
_SAMPLE_RATE = 24000
_SAMPLE_WIDTH = 2
_STDERR_EXCERPT_CHARS = 300
_PROCESS_TIMEOUT_SECONDS = 60.0
_OPUS_ARGS = ("-c:a", "libopus", "-b:a", "32k", "-f", "ogg")
_MP3_ARGS = ("-c:a", "libmp3lame", "-b:a", "64k", "-f", "mp3")

CLOUD_TTS_VOICES: tuple[str, ...] = (
    "Mer-Operator",
    "Kaz-Lifelike",
    "Tsb-Freespeech",
    "Gli-Operator",
    "Gli-Freespeech",
    "Bab-Debate",
    "Bab-Energetic",
    "Bab-Freespeech",
    "Tsb-Hesitating",
)

FetchAudio = Callable[[str, str], Awaitable[bytes]]


class CloudTextToSpeech:
    """SaluteSpeech over the Cloud.ru realtime gateway.

    The gateway answers with 24 kHz PCM deltas on a websocket; ffmpeg wraps the
    collected stream into the container the client asked for.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        fetch: FetchAudio | None = None,
        ffmpeg: str | None = None,
    ) -> None:
        self._settings = settings
        self._fetch = fetch or self._fetch_pcm
        self._ffmpeg = ffmpeg or settings.ffmpeg_binary

    async def synthesize(
        self,
        text: str,
        *,
        audio_format: str | None = None,
        voice: str | None = None,
    ) -> bytes:
        normalized = " ".join((text or "").split())
        if not normalized:
            return b""
        if not self._settings.cloud_tts_available:
            raise ConfigurationError(
                "CLOUD_TTS_API_KEY не задан: укажите ключ Cloud.ru Foundation Models"
            )
        pcm = await self._fetch(normalized[:_MAX_TEXT_CHARS], voice or self._settings.cloud_tts_voice)
        if not pcm:
            raise SpeechSynthesisError("Cloud.ru вернул пустое аудио")
        wav = _pcm_to_wav(pcm)
        requested = (audio_format or "opus").lower()
        if requested in {"wav", "wav16", "pcm16"}:
            return wav
        return await self._to_container(wav, "mp3" if requested == "mp3" else "ogg")

    async def close(self) -> None:
        return None

    async def _fetch_pcm(self, text: str, voice: str) -> bytes:
        from websockets.asyncio.client import connect

        payload = {
            "type": "response.create",
            "model": self._settings.cloud_tts_model,
            "response": {
                "output_modalities": ["audio"],
                "audio": {
                    "output": {
                        "format": {"type": "audio/pcm", "rate": _SAMPLE_RATE},
                        "voice": voice,
                        "speed": 1.0,
                    }
                },
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": text}],
                    }
                ],
            },
        }
        audio = bytearray()
        deadline = self._settings.cloud_tts_timeout_seconds
        try:
            async with asyncio.timeout(deadline):
                async with connect(
                    self._settings.cloud_tts_url,
                    additional_headers={"Authorization": f"Bearer {self._settings.cloud_tts_api_key.strip()}"},
                    open_timeout=15,
                    max_size=None,
                    close_timeout=5,
                ) as socket:
                    await socket.send(_json(payload))
                    async for raw in socket:
                        event = _json_loads(raw)
                        if event is None:
                            continue
                        kind = event.get("type")
                        if kind == "response.output_audio.delta":
                            delta = event.get("delta")
                            if isinstance(delta, str) and delta:
                                audio.extend(base64.b64decode(delta))
                        elif kind == "error":
                            raise SpeechSynthesisError(f"Cloud.ru TTS: {_short(event)}")
                        elif kind == "response.done":
                            status = (event.get("response") or {}).get("status")
                            if status in {"failed", "cancelled", "incomplete"}:
                                raise SpeechSynthesisError(f"Cloud.ru TTS: статус {status}")
                            break
        except TimeoutError as error:
            raise SpeechSynthesisError("Cloud.ru TTS не ответил вовремя") from error
        except SpeechSynthesisError:
            raise
        except Exception as error:  # noqa: BLE001 - transport failures become a spoken fallback
            log.warning("cloud tts transport failed: %s", error)
            raise SpeechSynthesisError("Cloud.ru TTS недоступен") from error
        return bytes(audio)

    async def _to_container(self, wav: bytes, container: str) -> bytes:
        with TemporaryDirectory(prefix="cloud-tts-") as directory:
            workdir = Path(directory)
            source = workdir / "speech.wav"
            source.write_bytes(wav)
            target = workdir / f"speech.{container}"
            args = _MP3_ARGS if container == "mp3" else _OPUS_ARGS
            await self._run_ffmpeg([self._ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), *args, str(target)])
            if not target.is_file() or target.stat().st_size == 0:
                raise SpeechSynthesisError("ffmpeg produced no audio")
            return target.read_bytes()

    async def _run_ffmpeg(self, args: list[str]) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as error:
            raise ConfigurationError(f"ffmpeg is not installed: {self._ffmpeg}") from error
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=_PROCESS_TIMEOUT_SECONDS)
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise SpeechSynthesisError("ffmpeg timed out") from error
        if process.returncode != 0:
            excerpt = stderr.decode("utf-8", "replace").strip()[:_STDERR_EXCERPT_CHARS]
            log.warning("ffmpeg failed with %s: %s", process.returncode, excerpt)
            raise SpeechSynthesisError(f"ffmpeg exited with {process.returncode}")


def _pcm_to_wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(_SAMPLE_WIDTH)
        stream.setframerate(_SAMPLE_RATE)
        stream.writeframes(pcm)
    return buffer.getvalue()


def _json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


def _json_loads(raw: Any) -> dict[str, Any] | None:
    import json

    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "replace")
    if not isinstance(raw, str):
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _short(event: dict[str, Any]) -> str:
    message = event.get("error") or event.get("message") or event
    text = str(message)
    return text[:200]
