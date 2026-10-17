import asyncio
import os
import re
import shutil
import tempfile
from pathlib import Path

from app.core.exceptions import ConfigurationError, TranscriptionError
from app.core.logger import get_logger

log = get_logger(__name__)

_DURATION_PATTERN = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_PROCESS_TIMEOUT_SECONDS = 120.0
_WAV_HEADER_BYTES = 44
_SAFE_SUFFIX_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-")


class AudioConverter:
    def __init__(
        self,
        ffmpeg_binary: str = "ffmpeg",
        sample_rate: int = 16000,
        max_duration_seconds: int = 120,
    ) -> None:
        self._ffmpeg_binary = ffmpeg_binary
        self._sample_rate = sample_rate
        self._max_duration_seconds = max_duration_seconds

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    async def to_wav(self, data: bytes, source_hint: str | None = None) -> bytes:
        if not data:
            raise TranscriptionError("аудиофайл пуст")

        with tempfile.TemporaryDirectory(prefix="stt-convert-") as workspace:
            source = Path(workspace) / f"source{_safe_suffix(source_hint)}"
            source.write_bytes(data)
            duration = await self._probe_file(source)
            if duration > self._max_duration_seconds:
                raise TranscriptionError(
                    f"аудио длится {duration:.1f} с, допустимо не более {self._max_duration_seconds} с"
                )
            target = Path(workspace) / "result.wav"
            await self._convert_file(source, target)
            if not target.exists():
                raise TranscriptionError("ffmpeg не создал выходной файл")
            wav = target.read_bytes()

        if len(wav) <= _WAV_HEADER_BYTES or not wav.startswith(b"RIFF") or wav[8:12] != b"WAVE":
            raise TranscriptionError("ffmpeg вернул данные, не являющиеся WAV")
        log.info("audio converted to %s Hz mono WAV, %.1f s, %s bytes", self._sample_rate, duration, len(wav))
        return wav

    async def probe_duration(self, data: bytes) -> float:
        if not data:
            raise TranscriptionError("аудиофайл пуст")
        with tempfile.TemporaryDirectory(prefix="stt-probe-") as workspace:
            source = Path(workspace) / "source.bin"
            source.write_bytes(data)
            return await self._probe_file(source)

    async def _probe_file(self, path: Path) -> float:
        duration = await self._probe_with_ffprobe(path)
        if duration is None:
            duration = await self._probe_with_ffmpeg(path)
        if duration is None or duration <= 0:
            raise TranscriptionError("не удалось определить длительность аудио: файл повреждён или не является аудио")
        return duration

    async def _probe_with_ffprobe(self, path: Path) -> float | None:
        ffprobe = self._ffprobe_binary()
        if ffprobe is None:
            return None
        stdout, _ = await self._run(
            ffprobe,
            [
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
        )
        try:
            duration = float(stdout.strip())
        except ValueError:
            return None
        return duration if duration > 0 else None

    async def _probe_with_ffmpeg(self, path: Path) -> float | None:
        _, stderr = await self._run(self._ffmpeg_binary, ["-hide_banner", "-nostdin", "-i", str(path)])
        match = _DURATION_PATTERN.search(stderr)
        if match is None:
            return None
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    async def _convert_file(self, source: Path, target: Path) -> None:
        _, stderr = await self._run(
            self._ffmpeg_binary,
            [
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(self._sample_rate),
                "-acodec",
                "pcm_s16le",
                "-f",
                "wav",
                str(target),
            ],
        )
        if not target.exists():
            raise TranscriptionError(f"ffmpeg не смог конвертировать аудио: {stderr.strip()[:300]}")

    async def _run(self, binary: str, args: list[str]) -> tuple[str, str]:
        try:
            process = await asyncio.create_subprocess_exec(
                binary,
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise ConfigurationError(f"аудиоутилита не найдена: {binary}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=_PROCESS_TIMEOUT_SECONDS
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            process.kill()
            await process.wait()
            raise TranscriptionError(f"{binary} не завершился за {_PROCESS_TIMEOUT_SECONDS:.0f} с") from exc
        return stdout.decode(errors="replace"), stderr.decode(errors="replace")

    def _ffprobe_binary(self) -> str | None:
        if os.sep in self._ffmpeg_binary:
            sibling = Path(self._ffmpeg_binary).with_name("ffprobe")
            return str(sibling) if sibling.is_file() else None
        return shutil.which("ffprobe")


def _safe_suffix(source_hint: str | None) -> str:
    if not source_hint:
        return ".bin"
    candidate = source_hint.strip().lower().rsplit("/", 1)[-1]
    if not candidate.startswith("."):
        candidate = f".{candidate}"
    if len(candidate) <= 6 and all(char in _SAFE_SUFFIX_CHARS for char in candidate):
        return candidate
    return ".bin"
