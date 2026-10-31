import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import ConfigurationError, ExternalServiceError, LLMError
from app.core.logger import get_logger
from app.core.oauth import SberOAuthClient

log = get_logger(__name__)

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3


@dataclass
class FunctionCall:
    name: str
    arguments: str


@dataclass
class ChatCompletion:
    content: str
    function_call: FunctionCall | None = None
    finish_reason: str | None = None


class GigaChatClient:
    """Асинхронный клиент GigaChat chat/completions с вызовом инструментов."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.gigachat_timeout_seconds),
            verify=settings.tls_verify,
        )
        self._oauth = SberOAuthClient(settings.gigachat_auth_url, self._client)
        self._closed = False

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatCompletion:
        if not self._settings.gigachat_enabled:
            raise ConfigurationError("GIGACHAT_CREDENTIALS is not configured")

        payload: dict[str, Any] = {
            "model": self._settings.gigachat_model,
            "messages": messages,
            "temperature": self._settings.gigachat_temperature if temperature is None else temperature,
            "max_tokens": self._settings.gigachat_max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        if tools:
            payload["functions"] = tools
            payload["function_call"] = "auto"

        data = await self._request(payload)
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("GigaChat returned no choices")

        choice = choices[0]
        message = choice.get("message") or {}
        raw_call = message.get("function_call")
        function_call = None
        if raw_call and raw_call.get("name"):
            function_call = FunctionCall(
                name=raw_call["name"],
                arguments=raw_call.get("arguments") or "{}",
            )
        return ChatCompletion(
            content=(message.get("content") or "").strip(),
            function_call=function_call,
            finish_reason=choice.get("finish_reason"),
        )

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error = "unknown error"
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            token = await self._oauth.get_token(
                self._settings.gigachat_credentials, self._settings.gigachat_scope
            )
            try:
                response = await self._client.post(
                    f"{self._settings.gigachat_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                )
            except httpx.HTTPError as error:
                last_error = f"network error: {error}"
                log.warning("gigachat request failed (attempt %s): %s", attempt, error)
                await asyncio.sleep(attempt)
                continue

            if response.status_code == 401:
                self._oauth.invalidate(self._settings.gigachat_scope)
                last_error = "401 unauthorized"
                continue
            if response.status_code in _RETRY_STATUSES:
                last_error = f"{response.status_code} {response.text[:200]}"
                log.warning("gigachat answered %s (attempt %s)", response.status_code, attempt)
                await asyncio.sleep(attempt)
                continue
            if response.status_code != 200:
                raise LLMError(f"GigaChat: {response.status_code} {response.text[:300]}")

            try:
                return response.json()
            except json.JSONDecodeError as error:
                raise LLMError("GigaChat returned malformed JSON") from error

        raise LLMError(f"GigaChat is unavailable after {_MAX_ATTEMPTS} attempts: {last_error}")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()


__all__ = ["ChatCompletion", "ExternalServiceError", "FunctionCall", "GigaChatClient"]
