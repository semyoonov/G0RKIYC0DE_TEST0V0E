from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.enums import Platform


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "gorkycode-assistant"
    environment: str = "local"
    log_level: str = "INFO"
    timezone: str = "Europe/Moscow"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/gorkycode"
    db_echo: bool = False
    auto_create_tables: bool = True

    redis_url: str = "redis://localhost:6379/0"
    cache_enabled: bool = True
    cache_ttl_seconds: int = 60
    conversation_history_turns: int = 8

    gigachat_credentials: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_base_url: str = "https://gigachat.devices.sberbank.ru/api/v1"
    gigachat_model: str = "GigaChat"
    gigachat_temperature: float = 0.1
    gigachat_max_tokens: int = 1024
    gigachat_timeout_seconds: float = 60.0
    gigachat_verify_ssl: bool = True
    sber_ca_bundle: str | None = None

    sber_tts_credentials: str = ""
    sber_tts_scope: str = "SALUTE_SPEECH_PERS"
    sber_tts_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    sber_tts_url: str = "https://smartspeech.sber.ru/rest/v1/text:synthesize"
    sber_tts_voice: str = "Nec_24000"
    sber_tts_format: str = "opus"
    sber_tts_timeout_seconds: float = 60.0
    # auto: SaluteSpeech при наличии ключа, иначе локальный синтез; sber/local/off — принудительно
    tts_backend: str = "auto"
    local_tts_enabled: bool = False
    local_tts_binary: str = "espeak-ng"
    local_tts_voice: str = "ru"
    local_tts_speed: int = 150
    cloud_tts_api_key: str = ""
    cloud_tts_url: str = "wss://foundation-models.api.cloud.ru/v1/realtime"
    cloud_tts_model: str = "GigaChat/SaluteSpeech"
    cloud_tts_voice: str = "Mer-Operator"
    cloud_tts_timeout_seconds: float = 45.0

    vosk_model_path: str = "models/vosk-model-small-ru-0.22"
    ffmpeg_binary: str = "ffmpeg"
    audio_sample_rate: int = 16000
    audio_max_duration_seconds: int = 120

    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    enable_telegram: bool = True

    vk_bot_token: str = ""
    vk_bot_group_id: int = 0
    vk_mini_app_id: int = 0
    vk_mini_app_secret: str = ""
    vk_access_token: str = ""
    enable_vk: bool = True

    max_bot_username: str = ""
    max_bot_token: str = ""
    max_api_base_url: str = "https://platform-api2.max.ru"
    max_poll_timeout_seconds: int = 30
    enable_max: bool = True

    web_host: str = "0.0.0.0"
    web_port: int = 8000
    web_public_url: str = "http://localhost:8000"
    mini_app_public_url: str = ""
    session_secret: str = "dev-insecure-session-secret"
    session_ttl_seconds: int = 2592000
    link_code_ttl_seconds: int = 900

    # Email OTP authentication (Resend API). Keep the secrets only in .env.
    resend_api_key: str = ""
    email_from: str = ""
    email_code_secret: str = ""
    email_code_ttl_seconds: int = 600
    email_code_max_attempts: int = 5
    email_code_cooldown_seconds: int = 60
    ws_max_concurrent_streams: int = 4

    enable_scheduler: bool = True
    reminder_poll_seconds: int = 30
    reminder_lookahead_seconds: int = 60

    tool_max_iterations: int = 4
    default_event_duration_minutes: int = 60

    @property
    def gigachat_enabled(self) -> bool:
        return bool(self.gigachat_credentials.strip())

    @property
    def sber_tts_available(self) -> bool:
        return bool(self.sber_tts_credentials.strip())

    @property
    def cloud_tts_available(self) -> bool:
        return bool(self.cloud_tts_api_key.strip())

    @property
    def tts_voices(self) -> list[str]:
        from app.ai.tts.cloud_tts import CLOUD_TTS_VOICES

        return list(CLOUD_TTS_VOICES)

    @property
    def tts_voice(self) -> str:
        return self.cloud_tts_voice

    @property
    def resolved_tts_backend(self) -> str:
        backend = self.tts_backend.strip().lower()
        if backend in {"cloud", "sber", "local"}:
            return backend
        if self.cloud_tts_available:
            return "cloud"
        if self.sber_tts_available:
            return "sber"
        return "local"

    @property
    def tts_enabled(self) -> bool:
        backend = self.tts_backend.strip().lower()
        if backend == "off":
            return False
        if backend == "cloud":
            return self.cloud_tts_available
        if backend == "sber":
            return self.sber_tts_available
        if backend == "local":
            return self.local_tts_enabled
        return self.cloud_tts_available or self.sber_tts_available or self.local_tts_enabled

    @property
    def telegram_enabled(self) -> bool:
        return self.enable_telegram and bool(self.telegram_bot_token.strip())

    @property
    def max_enabled(self) -> bool:
        return self.enable_max and bool(self.max_bot_token.strip())

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def tls_verify(self) -> bool | str:
        return self.sber_ca_bundle or self.gigachat_verify_ssl

    @property
    def vk_enabled(self) -> bool:
        return self.enable_vk and bool(self.vk_bot_token.strip())

    @property
    def mini_app_base_url(self) -> str:
        return (self.mini_app_public_url or self.web_public_url).rstrip("/")

    def mini_app_link(self, platform: Platform, code: str | None = None) -> str | None:
        """Public URL that opens the assistant on one platform, optionally carrying a link code."""
        if platform is Platform.TELEGRAM:
            username = self.telegram_bot_username.strip().lstrip("@")
            if not username:
                return None
            start = f"?start={code}" if code else ""
            return f"https://t.me/{username}{start}"
        if platform is Platform.MAX:
            username = self.max_bot_username.strip().lstrip("@")
            startapp = f"?startapp={code}" if code else ""
            return f"https://max.ru/{username}{startapp}" if username else None
        if platform is Platform.VK:
            return f"https://vk.com/app{self.vk_mini_app_id}" if self.vk_mini_app_id else None
        if platform is Platform.WEB:
            return f"{self.mini_app_base_url}/?link={code}" if code else f"{self.mini_app_base_url}/"
        return None

    def mini_app_links(self, code: str | None = None) -> dict[str, str | None]:
        return {platform.value: self.mini_app_link(platform, code) for platform in Platform}


@lru_cache
def get_settings() -> Settings:
    return Settings()
