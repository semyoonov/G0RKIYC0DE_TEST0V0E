from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from app.domain.enums import Platform
from app.services.auth.launch import (
    LaunchError,
    LaunchNotConfigured,
    max_identity,
    parse_launch_params,
    telegram_identity,
    vk_identity,
)

TELEGRAM_TOKEN = "8960478261:test-token"
MAX_TOKEN = "max-test-token"
VK_SECRET = "vk-test-secret"
VK_APP_ID = 51700000


def _signed_params(params: dict[str, str], token: str, *, exclude: set[str]) -> dict[str, str]:
    check = "\n".join(f"{key}={params[key]}" for key in sorted(params) if key not in exclude)
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signed = dict(params)
    signed["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return signed


def telegram_init_data(
    *,
    user: dict | None = None,
    auth_date: int | None = None,
    token: str = TELEGRAM_TOKEN,
) -> str:
    params = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAH-query",
        "user": json.dumps(
            user or {"id": 42, "first_name": "Аня", "last_name": "Петрова", "username": "anya"},
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    }
    return urlencode(_signed_params(params, token, exclude={"hash"}))


def max_init_data(*, user: dict | None = None, token: str = MAX_TOKEN) -> str:
    params = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(
            user or {"id": 77, "first_name": "Максим", "username": "maxim"},
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        "signature": "ignored-by-the-signature",
    }
    return urlencode(_signed_params(params, token, exclude={"hash", "signature"}))


def vk_launch_params(
    *,
    user_id: int = 555,
    secret: str = VK_SECRET,
    app_id: int = VK_APP_ID,
    urlsafe: bool = False,
) -> str:
    params = {
        "vk_access_token_settings": "",
        "vk_app_id": str(app_id),
        "vk_are_notifications_enabled": "0",
        "vk_is_app_user": "1",
        "vk_language": "ru",
        "vk_platform": "mobile_web",
        "vk_ref": "other",
        "vk_ts": str(int(time.time())),
        "vk_user_id": str(user_id),
    }
    check = "&".join(f"{key}={params[key]}" for key in sorted(params) if key.startswith("vk_"))
    signature = hmac.new(secret.encode(), check.encode(), hashlib.sha256).digest()
    if urlsafe:
        params["sign"] = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    else:
        params["sign"] = base64.b64encode(signature).decode()
    return urlencode(params)


def test_parse_launch_params_accepts_hash_and_query() -> None:
    assert parse_launch_params("?a=1&b=2") == {"a": "1", "b": "2"}
    assert parse_launch_params("#a=1&b=2") == {"a": "1", "b": "2"}


def test_telegram_init_data_is_accepted() -> None:
    context = telegram_identity(telegram_init_data(), TELEGRAM_TOKEN)

    assert context.identity.platform is Platform.TELEGRAM
    assert context.identity.external_id == "42"
    assert context.identity.display_name == "Аня Петрова"


def test_telegram_init_data_rejects_tampering() -> None:
    raw = telegram_init_data().replace("query_id=AAH-query", "query_id=AAH-other")

    with pytest.raises(LaunchError):
        telegram_identity(raw, TELEGRAM_TOKEN)


def test_telegram_init_data_rejects_expired_auth_date() -> None:
    raw = telegram_init_data(auth_date=int(time.time()) - 2 * 24 * 60 * 60)

    with pytest.raises(LaunchError):
        telegram_identity(raw, TELEGRAM_TOKEN)


def test_telegram_init_data_requires_configured_token() -> None:
    with pytest.raises(LaunchNotConfigured):
        telegram_identity(telegram_init_data(), "")


def test_max_init_data_is_accepted_and_skips_signature() -> None:
    context = max_identity(max_init_data(), MAX_TOKEN)

    assert context.identity.platform is Platform.MAX
    assert context.identity.external_id == "77"
    assert context.identity.display_name == "Максим"


def test_max_init_data_rejects_foreign_token() -> None:
    with pytest.raises(LaunchError):
        max_identity(max_init_data(), "other-token")


def test_vk_launch_params_are_accepted() -> None:
    context = vk_identity(vk_launch_params(), VK_SECRET, app_id=VK_APP_ID)

    assert context.identity.platform is Platform.VK
    assert context.identity.external_id == "555"
    assert context.language == "ru"


def test_vk_launch_params_reject_wrong_secret() -> None:
    with pytest.raises(LaunchError):
        vk_identity(vk_launch_params(), "wrong-secret", app_id=VK_APP_ID)


def test_vk_launch_params_reject_foreign_app() -> None:
    with pytest.raises(LaunchError):
        vk_identity(vk_launch_params(), VK_SECRET, app_id=1)


def test_vk_launch_params_require_secret() -> None:
    with pytest.raises(LaunchNotConfigured):
        vk_identity(vk_launch_params(), "")


def test_vk_official_urlsafe_sign_accepted() -> None:
    params = {
        "vk_access_token_settings": "",
        "vk_app_id": str(VK_APP_ID),
        "vk_are_notifications_enabled": "0",
        "vk_is_app_user": "1",
        "vk_language": "ru",
        "vk_platform": "mobile_web",
        "vk_ref": "other",
        "vk_ts": str(int(time.time())),
        "vk_user_id": "777",
    }
    check = urlencode([(k, params[k]) for k in sorted(params) if k.startswith("vk_")])
    sig = hmac.new(VK_SECRET.encode(), check.encode(), hashlib.sha256).digest()
    params["sign"] = base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
    raw = urlencode(params)

    context = vk_identity(raw, VK_SECRET, app_id=VK_APP_ID)
    assert context.identity.platform is Platform.VK
    assert context.identity.external_id == "777"

