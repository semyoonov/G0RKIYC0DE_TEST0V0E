from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from app.core.config import Settings
from app.core.exceptions import ConfigurationError, SpeechSynthesisError
from app.core.logger import get_logger

log = get_logger(__name__)

_MAX_TEXT_CHARS = 2000
_STDERR_EXCERPT_CHARS = 300
_PROCESS_TIMEOUT_SECONDS = 60.0
_OPUS_ARGS = ("-c:a", "libopus", "-b:a", "32k", "-f", "ogg")
_MP3_ARGS = ("-c:a", "libmp3lame", "-b:a", "64k", "-f", "mp3")


class LocalTextToSpeech:
    """Офлайн-синтез: espeak-ng озвучивает текст, ffmpeg упаковывает его в нужный контейнер.

    Ни ключей, ни сети не нужно — голосовые ответы работают, пока ключ SaluteSpeech не
    выдан; переключение обратно — `TTS_BACKEND=sber`.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        binary: str | None = None,
        ffmpeg: str | None = None,
    ) -> None:
        self._binary = binary or settings.local_tts_binary
        self._ffmpeg = ffmpeg or settings.ffmpeg_binary
        self._voice = settings.local_tts_voice
        self._speed = settings.local_tts_speed

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
        requested = (audio_format or "opus").lower()
        with tempfile.TemporaryDirectory(prefix="local-tts-") as directory:
            workdir = Path(directory)
            wav_path = workdir / "speech.wav"
            await self._run(
                [
                    self._binary,
                    "-v",
                    voice or self._voice,
                    "-s",
                    str(self._speed),
                    "-w",
                    str(wav_path),
                    normalized[:_MAX_TEXT_CHARS],
                ],
                what="espeak-ng",
            )
            if not wav_path.is_file() or wav_path.stat().st_size == 0:
                raise SpeechSynthesisError("espeak-ng produced no audio")
            if requested in {"wav", "wav16", "pcm16"}:
                return wav_path.read_bytes()
            target = workdir / ("speech.mp3" if requested == "mp3" else "speech.ogg")
            container = _MP3_ARGS if requested == "mp3" else _OPUS_ARGS
            await self._run(
                [
                    self._ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(wav_path),
                    *container,
                    str(target),
                ],
                what="ffmpeg",
            )
            if not target.is_file() or target.stat().st_size == 0:
                raise SpeechSynthesisError("ffmpeg produced no audio")
            return target.read_bytes()

    async def close(self) -> None:
        return None

    async def _run(self, args: list[str], *, what: str) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as error:
            raise ConfigurationError(f"{what} is not installed: {self._binary}") from error
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=_PROCESS_TIMEOUT_SECONDS)
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise SpeechSynthesisError(f"{what} timed out") from error
        if process.returncode != 0:
            excerpt = stderr.decode("utf-8", "replace").strip()[:_STDERR_EXCERPT_CHARS]
            log.warning("%s failed with %s: %s", what, process.returncode, excerpt)
            raise SpeechSynthesisError(f"{what} exited with {process.returncode}")
