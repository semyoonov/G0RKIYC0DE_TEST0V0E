from __future__ import annotations

from app.core.config import Settings
from app.domain.enums import Platform
from app.domain.identity import Identity

LINK_TEXT = (
    "Код привязки аккаунта: {code}\n"
    "Введите его в приложении или откройте {web_link}\n"
    "Код действует {minutes} мин и срабатывает один раз."
)

APP_TEXT = "Приложение ассистента: {link}"


def identity_for(platform: Platform, external_id: int | str, display_name: str | None = None) -> Identity:
    return Identity(platform=platform, external_id=str(external_id), display_name=display_name)


def display_name_of(*parts: str | None) -> str | None:
    name = " ".join(part.strip() for part in parts if part and part.strip())
    return name or None


def link_code_text(settings: Settings, code: str) -> str:
    minutes = max(1, settings.link_code_ttl_seconds // 60)
    web_link = settings.mini_app_link(Platform.WEB, code) or settings.mini_app_base_url
    return LINK_TEXT.format(code=code, web_link=web_link, minutes=minutes)


def app_text(settings: Settings) -> str:
    return APP_TEXT.format(link=settings.mini_app_base_url)
