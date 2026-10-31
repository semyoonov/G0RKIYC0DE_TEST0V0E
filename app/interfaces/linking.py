from __future__ import annotations

from app.core.config import Settings
from app.domain.enums import Platform
from app.domain.identity import Identity

APP_TEXT = "Приложение ассистента: {link}"


def identity_for(platform: Platform, external_id: int | str, display_name: str | None = None) -> Identity:
    return Identity(platform=platform, external_id=str(external_id), display_name=display_name)


def display_name_of(*parts: str | None) -> str | None:
    name = " ".join(part.strip() for part in parts if part and part.strip())
    return name or None


def app_text(settings: Settings) -> str:
    return APP_TEXT.format(link=settings.mini_app_base_url)
