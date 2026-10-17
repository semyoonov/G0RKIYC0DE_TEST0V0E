import base64
import time
import uuid
from dataclasses import dataclass

import httpx

from app.core.exceptions import ExternalServiceError
from app.core.logger import get_logger

log = get_logger(__name__)

_EXPIRY_MARGIN_SECONDS = 120


@dataclass
class _CachedToken:
    value: str
    expires_at: float


class SberOAuthClient:
    """Access tokens for Sber APIs (GigaChat, SaluteSpeech) sharing one OAuth endpoint."""

    def __init__(self, auth_url: str, client: httpx.AsyncClient, verify: bool | str = True) -> None:
        self._auth_url = auth_url
        self._client = client
        self._verify = verify
        self._tokens: dict[str, _CachedToken] = {}

    async def get_token(self, credentials: str, scope: str) -> str:
        if not credentials.strip():
            raise ExternalServiceError("sber-oauth", f"credentials for scope {scope} are not configured")
        cached = self._tokens.get(scope)
        now = time.time()
        if cached and cached.expires_at - _EXPIRY_MARGIN_SECONDS > now:
            return cached.value

        response = await self._client.post(
            self._auth_url,
            headers={
                "Authorization": f"Basic {credentials.strip()}",
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            content=f"scope={scope}",
        )
        if response.status_code != 200:
            raise ExternalServiceError(
                "sber-oauth",
                f"token request failed: {response.status_code} {response.text[:200]}",
                status_code=response.status_code,
            )

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise ExternalServiceError("sber-oauth", "token response has no access_token")

        expires_at = _parse_expiry(payload.get("expires_at"), now)
        self._tokens[scope] = _CachedToken(value=token, expires_at=expires_at)
        log.info("oauth token received for scope %s, valid until %s", scope, int(expires_at))
        return token

    def invalidate(self, scope: str | None = None) -> None:
        if scope is None:
            self._tokens.clear()
        else:
            self._tokens.pop(scope, None)


def _parse_expiry(raw: object, now: float) -> float:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return now + 25 * 60
    if value > 1e11:
        return value / 1000
    return value


def credentials_header(client_id: str, client_secret: str) -> str:
    """Build the Basic credential string Sber expects from a client id/secret pair."""
    return base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
