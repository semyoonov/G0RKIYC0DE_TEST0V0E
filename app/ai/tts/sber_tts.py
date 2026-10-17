import httpx

from app.core.config import Settings
from app.core.exceptions import (
    ConfigurationError,
    ExternalServiceError,
    SpeechSynthesisError,
)
from app.core.logger import get_logger
from app.core.oauth import SberOAuthClient

log = get_logger(__name__)

_MAX_TEXT_CHARS = 4000
_BODY_EXCERPT_CHARS = 200
_SUPPORTED_FORMATS = frozenset({"opus", "mp3", "wav16", "pcm16"})
_FALLBACK_FORMAT = "opus"
_SENTENCE_BOUNDARIES = (". ", "! ", "? ", "… ", "\n")


class SberTextToSpeech:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient(verify=settings.tls_verify)
        self._oauth = SberOAuthClient(
            settings.sber_tts_auth_url,
            self._client,
            verify=settings.tls_verify,
        )
        self._closed = False

    async def synthesize(
        self,
        text: str,
        *,
        audio_format: str | None = None,
        voice: str | None = None,
    ) -> bytes:
        if not text or not text.strip():
            return b""
        if not self._settings.sber_tts_credentials.strip():
            raise ConfigurationError(
                "sber_tts_credentials не заданы: укажите client_id:client_secret SaluteSpeech"
            )

        payload = self._prepare_text(text)
        try:
            token = await self._oauth.get_token(
                self._settings.sber_tts_credentials,
                self._settings.sber_tts_scope,
            )
        except ExternalServiceError as exc:
            raise SpeechSynthesisError(f"не удалось авторизоваться в SaluteSpeech: {exc}") from exc

        try:
            response = await self._client.post(
                self._settings.sber_tts_url,
                params={
                    "format": self._resolve_format(audio_format),
                    "voice": self._resolve_voice(voice),
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/text",
                },
                content=payload.encode("utf-8"),
                timeout=self._settings.sber_tts_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise SpeechSynthesisError(f"SaluteSpeech недоступен: {exc}") from exc

        if response.status_code != 200:
            excerpt = " ".join(response.text.split())[:_BODY_EXCERPT_CHARS]
            raise SpeechSynthesisError(
                f"SaluteSpeech вернул статус {response.status_code}: {excerpt}"
            )
        audio = response.content
        if not audio:
            raise SpeechSynthesisError("SaluteSpeech вернул пустой аудиоответ")
        return audio

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()

    def _prepare_text(self, text: str) -> str:
        stripped = text.strip()
        if len(stripped) <= _MAX_TEXT_CHARS:
            return stripped

        window = stripped[:_MAX_TEXT_CHARS]
        limit = _MAX_TEXT_CHARS // 2
        cut = max(window.rfind(marker) for marker in _SENTENCE_BOUNDARIES)
        if cut >= limit:
            end = cut + 1
        else:
            end = window.rfind(" ")
            if end < limit:
                end = _MAX_TEXT_CHARS
        log.warning(
            "текст для синтеза обрезан с %s до %s символов по границе предложения или слова",
            len(stripped),
            end,
        )
        return window[:end].strip()

    def _resolve_format(self, audio_format: str | None) -> str:
        default = self._settings.sber_tts_format.strip().lower()
        if default not in _SUPPORTED_FORMATS:
            default = _FALLBACK_FORMAT
        if audio_format is None:
            return default
        candidate = audio_format.strip().lower()
        if not candidate:
            return default
        if candidate in _SUPPORTED_FORMATS:
            return candidate
        log.warning("формат %s не поддерживается SaluteSpeech, используется %s", candidate, default)
        return default

    def _resolve_voice(self, voice: str | None) -> str:
        if voice is not None and voice.strip():
            return voice.strip()
        return self._settings.sber_tts_voice
