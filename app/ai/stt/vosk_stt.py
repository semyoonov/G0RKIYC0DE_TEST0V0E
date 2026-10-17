import asyncio
import contextlib
import io
import json
import wave
from pathlib import Path

import vosk

from app.core.exceptions import ConfigurationError, TranscriptionError
from app.core.logger import get_logger

log = get_logger(__name__)

MODEL_DOWNLOAD_URL = "https://alphacephei.com/vosk/models"
_CHUNK_BYTES = 8192
_CONVERT_HINT = "сконвертируйте аудио в mono 16-bit PCM WAV через AudioConverter.to_wav"


class VoskSpeechRecognizer:
    def __init__(self, model_path: str, sample_rate: int = 16000) -> None:
        self._model_path = Path(model_path)
        self._sample_rate = sample_rate
        self._model: vosk.Model | None = None
        self._model_lock = asyncio.Lock()

    @property
    def available(self) -> bool:
        return self._model_path.is_dir()

    async def transcribe(self, wav_bytes: bytes) -> str:
        pcm = self._extract_pcm(wav_bytes)
        if not self.available:
            raise ConfigurationError(
                f"модель Vosk не найдена по пути {self._model_path}; "
                f"скачайте модель с {MODEL_DOWNLOAD_URL} и распакуйте её в этот каталог"
            )
        model = await self._ensure_model()
        text = await asyncio.to_thread(self._recognize, model, pcm)
        if not text:
            raise TranscriptionError("речь не распознана")
        return text

    async def warmup(self) -> bool:
        """Load the model ahead of the first request; False when it is not installed."""
        if not self.available:
            return False
        await self._ensure_model()
        return True

    async def open_stream(self, max_bytes: int | None = None) -> "StreamingSession":
        if not self.available:
            raise ConfigurationError(
                f"модель Vosk не найдена по пути {self._model_path}; "
                f"скачайте модель с {MODEL_DOWNLOAD_URL} и распакуйте её в этот каталог"
            )
        model = await self._ensure_model()
        session = StreamingSession(model, self._sample_rate, max_bytes=max_bytes)
        await session.start()
        return session

    async def _ensure_model(self) -> vosk.Model:
        if self._model is not None:
            return self._model
        async with self._model_lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load_model)
        return self._model

    def _load_model(self) -> vosk.Model:
        log.info("loading Vosk model from %s", self._model_path)
        try:
            return vosk.Model(str(self._model_path))
        except Exception as exc:
            raise ConfigurationError(
                f"не удалось загрузить модель Vosk из {self._model_path}: {exc}; "
                f"проверьте каталог и скачайте модель заново с {MODEL_DOWNLOAD_URL}"
            ) from exc

    def _recognize(self, model: vosk.Model, pcm: bytes) -> str:
        recognizer = vosk.KaldiRecognizer(model, self._sample_rate)
        parts: list[str] = []
        for start in range(0, len(pcm), _CHUNK_BYTES):
            if recognizer.AcceptWaveform(pcm[start : start + _CHUNK_BYTES]):
                parts.append(json.loads(recognizer.Result()).get("text", ""))
        parts.append(json.loads(recognizer.FinalResult()).get("text", ""))
        return " ".join(part.strip() for part in parts if part.strip()).strip()

    def _extract_pcm(self, wav_bytes: bytes) -> bytes:
        if len(wav_bytes) < 12 or not wav_bytes.startswith(b"RIFF") or wav_bytes[8:12] != b"WAVE":
            raise TranscriptionError(f"ожидался WAV-файл; {_CONVERT_HINT}")
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                frame_rate = wav.getframerate()
                if channels != 1 or sample_width != 2 or frame_rate != self._sample_rate:
                    raise TranscriptionError(
                        f"WAV должен быть mono 16-bit PCM {self._sample_rate} Hz, "
                        f"получено каналов={channels}, бит на сэмпл={sample_width * 8}, "
                        f"частота={frame_rate}; {_CONVERT_HINT}"
                    )
                return wav.readframes(wav.getnframes())
        except (wave.Error, EOFError) as exc:
            raise TranscriptionError(f"не удалось прочитать WAV: {exc}; {_CONVERT_HINT}") from exc


class StreamingSession:
    """Incremental recognition of one live PCM stream.

    KaldiRecognizer is not thread-safe, so all calls happen in the session's single
    worker task; frames are queued and the bounded queue provides backpressure.
    """

    _FRAME_QUEUE_SIZE = 50

    def __init__(self, model: vosk.Model, sample_rate: int = 16000, max_bytes: int | None = None) -> None:
        self._model = model
        self._sample_rate = sample_rate
        self._max_bytes = max_bytes
        self._recognizer: vosk.KaldiRecognizer | None = None
        self._frames: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=self._FRAME_QUEUE_SIZE)
        self._partials: asyncio.Queue[str | None] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._received = 0
        self._segments: list[str] = []
        self._last_partial = ""
        self._finished = False

    @property
    def received_bytes(self) -> int:
        return self._received

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._recognizer = await asyncio.to_thread(vosk.KaldiRecognizer, self._model, self._sample_rate)
        self._worker = asyncio.create_task(self._run(), name="vosk-stream")

    async def feed(self, frame: bytes) -> None:
        if not frame:
            return
        if self._finished:
            raise TranscriptionError("поток уже завершён")
        self._received += len(frame)
        if self._max_bytes is not None and self._received > self._max_bytes:
            raise TranscriptionError("аудио длиннее допустимого лимита")
        await self._frames.put(frame)

    async def next_partial(self) -> str | None:
        return await self._partials.get()

    async def finish(self) -> str:
        if self._finished:
            return self._joined_text()
        self._finished = True
        if self._worker is not None:
            await self._frames.put(None)
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None
        if self._recognizer is not None:
            raw = await asyncio.to_thread(self._recognizer.FinalResult)
            final = json.loads(raw).get("text", "").strip()
            if final:
                self._segments.append(final)
            self._recognizer = None
        await self._partials.put(None)
        return self._joined_text()

    async def close(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None
        self._recognizer = None
        self._finished = True
        await self._partials.put(None)

    async def _run(self) -> None:
        try:
            while True:
                frame = await self._frames.get()
                if frame is None:
                    return
                recognizer = self._recognizer
                if recognizer is None:
                    return
                completed = await asyncio.to_thread(recognizer.AcceptWaveform, frame)
                if completed:
                    raw = await asyncio.to_thread(recognizer.Result)
                    text = json.loads(raw).get("text", "").strip()
                    if text:
                        self._segments.append(text)
                    self._last_partial = ""
                    await self._partials.put("")
                    continue
                raw = await asyncio.to_thread(recognizer.PartialResult)
                partial = json.loads(raw).get("partial", "").strip()
                if partial and partial != self._last_partial:
                    self._last_partial = partial
                    await self._partials.put(partial)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a broken frame must not kill the connection silently
            log.exception("vosk streaming worker failed")

    def _joined_text(self) -> str:
        return " ".join(part for part in self._segments if part).strip()
