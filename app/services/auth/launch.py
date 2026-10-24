from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

from app.domain.enums import Platform
from app.domain.identity import Identity

WEBAPP_KEY = b"WebAppData"
DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60
_CLOCK_SKEW_SECONDS = 5 * 60


class LaunchError(ValueError):
    """Launch parameters are missing, forged or stale."""


class LaunchNotConfigured(LaunchError):
    """The platform is not configured, so its launch data cannot be validated."""


@dataclass(frozen=True, slots=True)
class LaunchContext:
    """What a validated mini-app launch tells us about the visitor."""

    identity: Identity
    start_param: str | None = None
    language: str | None = None


def _hmac_sha256(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def parse_launch_params(raw: str | None) -> dict[str, str]:
    """Parse `a=1&b=2`, `?a=1` and `#a=1` alike; every platform uses one of these."""
    if raw is None:
        raise LaunchError("launch parameters are empty")
    text = raw.strip()
    if text[:1] in {"?", "#"}:
        text = text[1:]
    if not text:
        raise LaunchError("launch parameters are empty")
    params: dict[str, str] = {}
    for key, value in parse_qsl(text, keep_blank_values=True):
        if key:
            params[key] = value
    if not params:
        raise LaunchError("launch parameters are empty")
    return params


def data_check_string(params: dict[str, str], exclude: set[str]) -> str:
    return "\n".join(f"{key}={params[key]}" for key in sorted(params) if key not in exclude)


def _vk_check_string(params: dict[str, str]) -> str:
    keys = sorted(key for key in params if key.startswith("vk_") and key != "sign")
    return "&".join(f"{key}={params[key]}" for key in keys)


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise LaunchError("user payload is not JSON") from error
    return parsed if isinstance(parsed, dict) else {}


def _display_name(user: dict[str, Any]) -> str | None:
    parts = [user.get("first_name"), user.get("last_name")]
    name = " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())
    if name:
        return name
    username = user.get("username")
    if isinstance(username, str) and username.strip():
        return f"@{username.strip()}"
    return None


def _start_param(params: dict[str, str]) -> str | None:
    for key in ("start_param", "startParam", "startapp", "start_app"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _language(params: dict[str, str], user: dict[str, Any]) -> str | None:
    candidates = (user.get("language_code"), params.get("language_code"), params.get("vk_language"))
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _check_age(issued_at: str | None, now: int, max_age_seconds: int) -> None:
    if issued_at is None or not issued_at.strip():
        return
    try:
        stamp = int(float(issued_at))
    except ValueError as error:
        raise LaunchError("launch timestamp is not a number") from error
    if stamp > now + _CLOCK_SKEW_SECONDS:
        raise LaunchError("launch timestamp is in the future")
    if now - stamp > max_age_seconds:
        raise LaunchError("launch parameters expired")


def telegram_identity(
    raw: str | None,
    bot_token: str,
    *,
    now: int | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> LaunchContext:
    """Validate Telegram WebApp initData (core.telegram.org/bots/webapps)."""
    if not bot_token.strip():
        raise LaunchNotConfigured("telegram bot token is not configured")
    params = parse_launch_params(raw)
    provided = params.get("hash", "").strip().lower()
    if not provided:
        raise LaunchError("telegram hash is missing")
    secret = _hmac_sha256(WEBAPP_KEY, bot_token.strip().encode("utf-8"))
    expected = _hmac_sha256(secret, data_check_string(params, {"hash"}).encode("utf-8")).hex()
    if not hmac.compare_digest(expected, provided):
        raise LaunchError("telegram signature mismatch")
    moment = int(now if now is not None else time.time())
    _check_age(params.get("auth_date"), moment, max_age_seconds)
    user = _json_object(params.get("user"))
    if user.get("id") is None:
        raise LaunchError("telegram user is missing")
    return LaunchContext(
        identity=Identity(Platform.TELEGRAM, str(user["id"]), _display_name(user)),
        start_param=_start_param(params),
        language=_language(params, user),
    )


def max_identity(
    raw: str | None,
    bot_token: str,
    *,
    now: int | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> LaunchContext:
    """Validate MAX WebApp initData (dev.max.ru/help/miniapps).

    The scheme matches Telegram's: `hash` signs a sorted `key=value` block with a
    key derived from the bot token, and `signature` (when MAX adds it) is excluded.
    """
    if not bot_token.strip():
        raise LaunchNotConfigured("max bot token is not configured")
    params = parse_launch_params(raw)
    provided = params.get("hash", "").strip().lower()
    if not provided:
        raise LaunchError("max hash is missing")
    secret = _hmac_sha256(WEBAPP_KEY, bot_token.strip().encode("utf-8"))
    expected = _hmac_sha256(secret, data_check_string(params, {"hash", "signature"}).encode("utf-8")).hex()
    if not hmac.compare_digest(expected, provided):
        raise LaunchError("max signature mismatch")
    moment = int(now if now is not None else time.time())
    _check_age(params.get("auth_date") or params.get("authDate"), moment, max_age_seconds)
    user = _json_object(params.get("user"))
    user_id = user.get("id") or params.get("user_id") or params.get("userId")
    if user_id is None or str(user_id).strip() == "":
        raise LaunchError("max user is missing")
    return LaunchContext(
        identity=Identity(Platform.MAX, str(user_id), _display_name(user)),
        start_param=_start_param(params),
        language=_language(params, user),
    )


def vk_identity(
    raw: str | None,
    app_secret: str,
    *,
    app_id: int | None = None,
    now: int | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> LaunchContext:
    """Validate VK Mini App launch parameters (dev.vk.com/ru/mini-apps).

    VK signs every `vk_*` parameter with the app secret and passes the result as
    `sign`; the signature is the base64 of HMAC-SHA256 over the sorted pairs.
    """
    if not app_secret.strip():
        raise LaunchNotConfigured("vk mini app secret is not configured")
    params = parse_launch_params(raw)
    provided = params.get("sign", "").strip()
    if not provided:
        raise LaunchError("vk sign is missing")
    signature = _hmac_sha256(app_secret.strip().encode("utf-8"), _vk_check_string(params).encode("utf-8"))
    expected = base64.b64encode(signature).decode("ascii")
    if not hmac.compare_digest(expected, provided):
        raise LaunchError("vk signature mismatch")
    if app_id and params.get("vk_app_id") and params["vk_app_id"] != str(app_id):
        raise LaunchError("vk app id mismatch")
    moment = int(now if now is not None else time.time())
    _check_age(params.get("vk_ts"), moment, max_age_seconds)
    user_id = params.get("vk_user_id", "").strip()
    if not user_id:
        raise LaunchError("vk user is missing")
    return LaunchContext(
        identity=Identity(Platform.VK, user_id, None),
        start_param=_start_param(params),
        language=params.get("vk_language"),
    )
