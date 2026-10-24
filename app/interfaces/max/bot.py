from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

import httpx

from app.core.exceptions import ExternalServiceError
from app.core.logger import get_logger
from app.interfaces.max.handlers import handle_update

if TYPE_CHECKING:
    from app.ai.assistant import AssistantService
    from app.core.config import Settings
    from app.services.auth.service import AuthService

log = get_logger(__name__)

_ERROR_EXCERPT_LIMIT = 300
_DEFAULT_TIMEOUT = 30.0
_UPLOAD_TIMEOUT = 120.0
_FAILURE_DELAY_SECONDS = 1.0
_AUDIO_CONTENT_TYPES = {
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
}


def _audio_content_type(filename: str) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _AUDIO_CONTENT_TYPES.get(extension, "application/octet-stream")


def inline_keyboard_attachment(buttons: list[list[dict[str, Any]]]) -> dict[str, Any]:
    return {"type": "inline_keyboard", "payload": {"buttons": buttons}}


class MaxClient:
    """Async client for the MAX Bot API."""

    def __init__(
        self,
        base_url: str,
        token: str,
        client: httpx.AsyncClient | None = None,
        *,
        verify: bool | str = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = client or httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            verify=verify,
            headers={"User-Agent": "gorkycode-assistant/1.0"},
        )

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": self._token}

    async def get_updates(self, marker: int | None = None, timeout: int = 30) -> dict[str, Any]:
        params: dict[str, Any] = {"timeout": timeout}
        if marker is not None:
            params["marker"] = marker
        return await self._get_json("/updates", params=params, timeout=timeout + _DEFAULT_TIMEOUT)

    async def send_text(
        self,
        user_id: int | str,
        text: str,
        buttons: list[list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text}
        if buttons:
            payload["attachments"] = [inline_keyboard_attachment(buttons)]
        return await self._post_json("/messages", params={"user_id": user_id}, payload=payload)

    async def answer_callback(self, callback_id: str) -> dict[str, Any]:
        return await self._post_json("/answers", params={"callback_id": callback_id}, payload={})

    async def send_audio(self, user_id: int | str, data: bytes, filename: str = "answer.opus") -> dict[str, Any]:
        token = await self._upload(data, filename, "audio")
        payload = {"attachments": [{"type": "audio", "payload": {"token": token}}]}
        return await self._post_json("/messages", params={"user_id": user_id}, payload=payload)

    async def download(self, url: str) -> bytes:
        target = f"{self._base_url}{url}" if url.startswith("/") else url
        response = await self._request("GET", target, timeout=_UPLOAD_TIMEOUT)
        if response.is_error:
            raise self._http_error(response)
        return response.content

    async def close(self) -> None:
        await self._client.aclose()

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"{self._base_url}{path}",
            headers=self._auth_headers,
            params=params,
            timeout=timeout,
        )
        return self._decode(response)

    async def _post_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            f"{self._base_url}{path}",
            headers=self._auth_headers,
            params=params,
            json=payload,
            timeout=_DEFAULT_TIMEOUT,
        )
        return self._decode(response)

    async def _upload(self, data: bytes, filename: str, upload_type: str) -> str:
        response = await self._request(
            "POST",
            f"{self._base_url}/uploads",
            headers=self._auth_headers,
            params={"type": upload_type},
            timeout=_UPLOAD_TIMEOUT,
        )
        upload_url = self._decode(response).get("url")
        if not isinstance(upload_url, str) or not upload_url:
            raise ExternalServiceError("max", "upload URL is missing in the response")

        uploaded = await self._request(
            "PUT",
            upload_url,
            files={"data": (filename, data, _audio_content_type(filename))},
            timeout=_UPLOAD_TIMEOUT,
        )
        token = self._decode(uploaded).get("token")
        if not isinstance(token, str) or not token:
            raise ExternalServiceError("max", "file token is missing in the upload response")
        return token

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            return await self._client.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ExternalServiceError("max", f"transport error: {exc}") from exc

    def _decode(self, response: httpx.Response) -> dict[str, Any]:
        if response.is_error:
            raise self._http_error(response)
        if not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise ExternalServiceError(
                "max",
                f"invalid JSON response: {exc}",
                status_code=response.status_code,
            ) from exc
        if not isinstance(payload, dict):
            raise ExternalServiceError("max", "unexpected response payload", status_code=response.status_code)
        return payload

    def _http_error(self, response: httpx.Response) -> ExternalServiceError:
        excerpt = " ".join(response.text.split())[:_ERROR_EXCERPT_LIMIT]
        return ExternalServiceError("max", f"{response.status_code} {excerpt}", status_code=response.status_code)


class MaxBot:
    """Long-polling MAX bot wired to the assistant service."""

    def __init__(
        self,
        assistant: AssistantService,
        settings: Settings,
        auth: AuthService | None = None,
    ) -> None:
        self._assistant = assistant
        self._settings = settings
        self._auth = auth
        self._client: MaxClient | None = None
        self._task: asyncio.Task[None] | None = None
        self._marker: int | None = None

    async def start(self) -> None:
        if not self._settings.max_enabled:
            log.warning("MAX bot is disabled: max_bot_token is not configured")
            return
        if self._task is not None and not self._task.done():
            return
        if self._client is None:
            self._log_tls_mode()
            self._client = MaxClient(
                self._settings.max_api_base_url,
                self._settings.max_bot_token,
                verify=self._settings.tls_verify,
            )
        self._task = asyncio.create_task(self._poll_loop(), name="max-polling")
        log.info("MAX bot polling started")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        client, self._client = self._client, None
        if client is not None:
            await client.close()
        log.info("MAX bot stopped")

    async def _poll_loop(self) -> None:
        client = self._client
        if client is None:
            return
        while True:
            try:
                payload = await client.get_updates(
                    self._marker,
                    timeout=self._settings.max_poll_timeout_seconds,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("MAX getUpdates failed: %s", exc)
                await asyncio.sleep(_FAILURE_DELAY_SECONDS)
                continue

            marker = payload.get("marker")
            if isinstance(marker, int):
                self._marker = marker
            for update in payload.get("updates") or []:
                if not isinstance(update, dict):
                    continue
                try:
                    await handle_update(
                        client,
                        update,
                        self._assistant,
                        self._settings.tz,
                        auth=self._auth,
                        settings=self._settings,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("MAX update handling failed")

    def _log_tls_mode(self) -> None:
        verify = self._settings.tls_verify
        if isinstance(verify, str):
            log.info("MAX: TLS verification uses CA bundle %s", verify)
        elif verify:
            log.warning(
                "MAX: TLS verification is enabled and platform-api2.max.ru is signed by the Минцифры root CA; "
                "if the handshake fails with a certificate error, set sber_ca_bundle to that CA or disable "
                "verification explicitly"
            )
        else:
            log.warning("MAX: TLS verification is disabled by configuration")
