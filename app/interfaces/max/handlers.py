from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from app.core.exceptions import AssistantError, ExternalServiceError
from app.core.logger import get_logger
from app.domain.enums import EventStatus, Platform
from app.interfaces.linking import app_text, display_name_of, identity_for, link_code_text
from app.interfaces.email_linking import confirm_email_link, request_email_link
from app.services.auth.service import LinkCodeError
from app.interfaces.cards import (
    action_label,
    cards_text,
    done_button,
    parse_done_callback,
    pending_events,
)

if TYPE_CHECKING:
    from app.ai.assistant import AssistantService
    from app.core.config import Settings
    from app.services.auth.service import AuthService
    from app.domain.models import AssistantResponse, EventRead
    from app.interfaces.max.bot import MaxClient

log = get_logger(__name__)

ERROR_REPLY = "Не получилось обработать запрос, попробуйте ещё раз."
GREETING = (
    "Привет! Я ассистент задач и встреч. Напишите или запишите голосом, что нужно запланировать: "
    "задачу, встречу или напоминание."
)
HELP = (
    "Я сохраняю задачи, встречи и напоминания и напоминаю о них. "
    "Напишите или запишите голосом, что и когда нужно сделать."
)
_AUDIO_ATTACHMENT_TYPES = {"audio", "voice"}


def _clean_code(raw: str | None) -> str:
    if not raw:
        return ""
    cleaned = raw.strip().lstrip("?#")
    if "=" in cleaned:
        for part in cleaned.split("&"):
            k, _, v = part.partition("=")
            if k in ("start", "startapp", "link", "code", "ref") and v.strip():
                return v.strip()
    return cleaned


async def _handle_start_flow(
    client: MaxClient,
    user_id: int | str,
    sender: dict[str, Any],
    raw_code: str,
    auth: AuthService | None,
) -> None:
    code = _clean_code(raw_code)
    if code and auth is not None:
        name = sender.get("name") or sender.get("first_name")
        identity = identity_for(
            Platform.MAX,
            user_id,
            display_name_of(name if isinstance(name, str) else None, sender.get("username")),
        )
        try:
            await auth.redeem(identity, code)
            log.info("MAX: redeemed link code %s for user %s", code, user_id)
            await client.send_text(
                user_id,
                "✅ Аккаунт успешно привязан!\n"
                "Теперь ваши задачи, встречи и напоминания синхронизированы между MAX и веб-версией.\n\n"
                f"{GREETING}",
            )
            return
        except LinkCodeError as exc:
            await client.send_text(
                user_id,
                f"❌ Не удалось привязать аккаунт: {exc}.\n\n"
                "Получите новый код в веб-приложении или используйте /link для создания кода.",
            )
            return
        except Exception:
            log.exception("MAX: link redeem failed for user %s", user_id)
            await client.send_text(user_id, "❌ Не удалось привязать аккаунт, попробуйте ещё раз.")
            return
    await client.send_text(user_id, GREETING)


async def handle_update(
    client: MaxClient,
    update: dict[str, Any],
    assistant: AssistantService,
    tz: ZoneInfo,
    *,
    auth: AuthService | None = None,
    settings: Settings | None = None,
) -> None:
    update_type = update.get("update_type")
    if update_type == "message_callback":
        await _handle_callback(client, update, assistant)
        return
    if update_type == "bot_started":
        sender = update.get("user") or {}
        user_id = sender.get("user_id") or update.get("chat_id")
        if user_id is None:
            log.warning("MAX bot_started update without user_id is skipped")
            return
        payload = update.get("payload")
        raw_code = str(payload).strip() if payload is not None else ""
        await _handle_start_flow(client, user_id, sender, raw_code, auth)
        return
    if update_type != "message_created":
        return
    message = update.get("message") or {}
    sender = message.get("sender") or {}
    user_id = sender.get("user_id")
    if user_id is None:
        log.warning("MAX update without sender.user_id is skipped")
        return

    body = message.get("body") or {}
    attachments = body.get("attachments") or []
    text = (body.get("text") or "").strip()

    if _find_audio(attachments) is None and text:
        command = text.split(maxsplit=1)[0].lower()
        if command == "/start":
            parts = text.split(maxsplit=1)
            raw_code = parts[1].strip() if len(parts) > 1 else ""
            await _handle_start_flow(client, user_id, sender, raw_code, auth)
            return
        if command == "/help":
            await client.send_text(user_id, HELP)
            return
        if command == "/link" and auth is not None and settings is not None:
            await _send_link_code(client, user_id, sender, auth, settings)
            return
        if command == "/email":
            if auth is None:
                await client.send_text(user_id, "Привязка по email временно недоступна.")
                return
            parts = text.split(maxsplit=1)
            if len(parts) != 2:
                await client.send_text(user_id, "Использование: /email ваш-адрес@example.com")
                return
            name = sender.get("name") or sender.get("first_name")
            identity = identity_for(
                Platform.MAX, user_id,
                display_name_of(name if isinstance(name, str) else None, sender.get("username")),
            )
            await client.send_text(user_id, await request_email_link(auth, identity, parts[1]))
            return
        if command == "/emailcode":
            if auth is None:
                await client.send_text(user_id, "Привязка по email временно недоступна.")
                return
            parts = text.split()
            if len(parts) != 3:
                await client.send_text(user_id, "Использование: /emailcode ваш-адрес@example.com 123456")
                return
            name = sender.get("name") or sender.get("first_name")
            identity = identity_for(
                Platform.MAX, user_id,
                display_name_of(name if isinstance(name, str) else None, sender.get("username")),
            )
            await client.send_text(user_id, await confirm_email_link(auth, identity, parts[1], parts[2]))
            return
        if command == "/app" and settings is not None:
            await client.send_text(user_id, app_text(settings))
            return

    try:
        response = await _run_assistant(client, assistant, user_id, text, attachments)
    except AssistantError:
        log.exception("MAX request failed for user %s", user_id)
        await client.send_text(user_id, ERROR_REPLY)
        return
    if response is not None:
        await _send_reply(client, user_id, response, tz)


async def _send_link_code(
    client: MaxClient,
    user_id: int | str,
    sender: dict[str, Any],
    auth: AuthService,
    settings: Settings,
) -> None:
    name = sender.get("name") or sender.get("first_name")
    identity = identity_for(
        Platform.MAX,
        user_id,
        display_name_of(name if isinstance(name, str) else None, sender.get("username")),
    )
    try:
        code = await auth.issue_link_code(identity)
    except Exception:  # noqa: BLE001 - a failed code must not kill the polling loop
        log.exception("MAX link code request failed for user %s", user_id)
        await client.send_text(user_id, "Не удалось создать код привязки, попробуйте ещё раз.")
        return
    await client.send_text(user_id, link_code_text(settings, code["code"]))


async def _handle_callback(client: MaxClient, update: dict[str, Any], assistant: AssistantService) -> None:
    callback = update.get("callback") or {}
    if not isinstance(callback, dict):
        log.warning("MAX callback update without callback object is skipped")
        return
    raw_payload = callback.get("payload")
    payload = raw_payload if isinstance(raw_payload, str) else ""
    user_id = _callback_user_id(update, callback)
    event_id = parse_done_callback(payload)
    if user_id is None or event_id is None:
        log.warning("MAX callback update without user or known payload is skipped: %r", raw_payload)
        return

    try:
        await assistant.set_event_status(Platform.MAX, str(user_id), event_id, EventStatus.DONE)
    except AssistantError:
        log.exception("MAX marking event %s as done failed", event_id)
        await client.send_text(user_id, ERROR_REPLY)
    await _acknowledge_callback(client, callback.get("callback_id"))


def _callback_user_id(update: dict[str, Any], callback: dict[str, Any]) -> int | str | None:
    user = callback.get("user")
    if isinstance(user, dict) and user.get("user_id") is not None:
        return user["user_id"]
    message = update.get("message") or {}
    sender = message.get("sender") if isinstance(message, dict) else None
    if isinstance(sender, dict) and sender.get("user_id") is not None:
        return sender["user_id"]
    return None


async def _acknowledge_callback(client: MaxClient, callback_id: Any) -> None:
    if not isinstance(callback_id, str) or not callback_id:
        return
    try:
        await client.answer_callback(callback_id)
    except ExternalServiceError as exc:
        log.warning("MAX callback %s acknowledgement failed: %s", callback_id, exc)


async def _run_assistant(
    client: MaxClient,
    assistant: AssistantService,
    user_id: int | str,
    text: str,
    attachments: list[Any],
) -> AssistantResponse | None:
    attachment = _find_audio(attachments)
    if attachment is not None:
        url = (attachment.get("payload") or {}).get("url")
        if not isinstance(url, str) or not url:
            raise ExternalServiceError("max", "audio attachment has no download url")
        audio = await client.download(url)
        return await assistant.handle_voice(Platform.MAX, str(user_id), audio, source_format=None, speak=False)
    if not text:
        return None
    return await assistant.handle_text(Platform.MAX, str(user_id), text)


def _find_audio(attachments: list[Any]) -> dict[str, Any] | None:
    for attachment in attachments:
        if isinstance(attachment, dict) and attachment.get("type") in _AUDIO_ATTACHMENT_TYPES:
            return attachment
    return None


def done_buttons(events: Sequence[EventRead]) -> list[list[dict[str, Any]]] | None:
    """MAX inline keyboard rows for the pending events of a card message."""
    rows: list[list[dict[str, Any]]] = []
    for event in pending_events(events):
        button = done_button(event)
        if button is None:
            continue
        text, payload = button
        rows.append([{"type": "callback", "text": text, "payload": payload}])
    return rows or None


async def _send_reply(
    client: MaxClient,
    user_id: int | str,
    response: AssistantResponse,
    tz: ZoneInfo,
) -> None:
    text = response.text.strip()
    if text:
        await client.send_text(user_id, text)
    if response.events:
        await client.send_text(
            user_id,
            cards_text(response.events, tz, action_label(response.intent)),
            buttons=done_buttons(response.events),
        )
