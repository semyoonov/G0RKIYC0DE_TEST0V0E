from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.domain.enums import Platform
from app.domain.identity import Identity

_MAX_TOKEN_LENGTH = 2048
_TOKEN_VERSION = 1


class SessionTokenError(ValueError):
    """Токен сессии отсутствует, испорчен, подделан или истёк."""


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as error:
        raise SessionTokenError("token payload is not base64") from error


class SessionTokens:
    """Компактные подписанные токены: `base64url(payload).base64url(hmac)`.

    В payload лежит платформенная идентичность, поэтому проверенный запуск мини-приложения
    и следующий за ним вызов API связаны между собой без серверного хранилища сессий.
    """

    def __init__(self, secret: str, ttl_seconds: int = 30 * 24 * 60 * 60) -> None:
        if not secret:
            raise ValueError("session secret must not be empty")
        self._secret = secret.encode("utf-8")
        self._ttl_seconds = ttl_seconds

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def issue(self, identity: Identity, *, now: float | None = None) -> str:
        issued_at = int(now if now is not None else time.time())
        body = {
            "v": _TOKEN_VERSION,
            "p": identity.platform.value,
            "e": identity.external_id,
            "n": identity.display_name,
            "i": issued_at,
            "x": issued_at + self._ttl_seconds,
        }
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{_b64encode(payload)}.{_b64encode(signature)}"

    def parse(self, token: str | None, *, now: float | None = None) -> Identity:
        if not token or len(token) > _MAX_TOKEN_LENGTH:
            raise SessionTokenError("token is missing")
        payload_part, _, signature_part = token.partition(".")
        if not payload_part or not signature_part:
            raise SessionTokenError("token is malformed")
        payload = _b64decode(payload_part)
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(signature_part)):
            raise SessionTokenError("token signature mismatch")
        try:
            body = json.loads(payload)
        except json.JSONDecodeError as error:
            raise SessionTokenError("token payload is not JSON") from error
        if not isinstance(body, dict) or body.get("v") != _TOKEN_VERSION:
            raise SessionTokenError("token version is unsupported")
        expires_at = body.get("x")
        if not isinstance(expires_at, int) or expires_at <= int(now if now is not None else time.time()):
            raise SessionTokenError("token expired")
        platform = body.get("p")
        external_id = body.get("e")
        if not isinstance(platform, str) or not isinstance(external_id, str) or not external_id:
            raise SessionTokenError("token identity is incomplete")
        try:
            parsed_platform = Platform(platform)
        except ValueError as error:
            raise SessionTokenError("token platform is unknown") from error
        display_name = body.get("n")
        return Identity(
            platform=parsed_platform,
            external_id=external_id,
            display_name=display_name if isinstance(display_name, str) else None,
        )
