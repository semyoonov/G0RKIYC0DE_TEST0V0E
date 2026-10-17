from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    vosk_model_path: str = "models/vosk-model-small-ru-0.22"
    ffmpeg_binary: str = "ffmpeg"
    audio_sample_rate: int = 16000
    audio_max_duration_seconds: int = 120

    telegram_bot_token: str = ""
    enable_telegram: bool = True
    max_bot_token: str = ""
    max_api_base_url: str = "https://platform-api2.max.ru"
    max_poll_timeout_seconds: int = 30
    enable_max: bool = True

    web_host: str = "0.0.0.0"
    web_port: int = 8000
    web_public_url: str = "http://localhost:8000"
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
    def tts_enabled(self) -> bool:
        return bool(self.sber_tts_credentials.strip())

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
