from __future__ import annotations

from app.core.config import Settings

APP_TEXT = "Приложение ассистента: {link}"


def app_text(settings: Settings) -> str:
    return APP_TEXT.format(link=settings.mini_app_base_url)
