from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from app.core.exceptions import ExternalServiceError
from app.core.logger import get_logger
from app.domain.enums import EventStatus, Platform
from app.interfaces.cards import action_label, cards_text, pending_events
from app.interfaces.linking import (
    app_text,
    display_name_of,
    identity_for,
    link_code_text,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from zoneinfo import ZoneInfo

    from vkbottle import API
    from vkbottle.bot import Message

    from app.ai.assistant import AssistantService
    from app.core.config import Settings
    from app.domain.models import AssistantResponse, EventRead
    from app.services.auth.service import AuthService

log = get_logger(__name__)

GREETING = (
    "Привет! Я ассистент задач и встреч. Напишите или запишите голосом, что нужно запланировать: "
    "задачу, встречу или напоминание."
)
HELP = (
    "Я сохраняю задачи, встречи и напоминания и напоминаю о них.\n"
    "Примеры: «Завтра в 10 встреча с командой», «Напомни в пятницу про отчёт».\n"
    "Можно отправлять голосовые — я распознаю речь.\n"
    "/link — код привязки аккаунта, /app — мини-приложение."
)
ERROR_REPLY = "Не получилось обработать запрос, попробуйте ещё раз."
QUICK_ACTIONS = ("Что у меня сегодня?", "Что на завтра?", "Что на этой неделе?")
AUDIO_ATTACHMENT_TYPES = {"audio_message", "audio"}
_DOWNLOAD_TIMEOUT_SECONDS = 60.0


def _attachment_url(attachment: Any) -> str | None:
    message = attachment.audio_message or attachment.audio
    if message is None:
        return None
    for attribute in ("link_ogg", "link_mp3", "url"):
        link = getattr(message, attribute, None)
        if isinstance(link, str) and link:
            return link
    return None


def _find_audio(attachments: Sequence[Any]) -> tuple[Any, str] | None:
    for attachment in attachments:
        if getattr(attachment, "type", None) not in AUDIO_ATTACHMENT_TYPES:
            continue
        url = _attachment_url(attachment)
        if url:
            return attachment, url
    return None


async def download_voice(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
        response = await client.get(url)
    if response.is_error:
        raise ExternalServiceError("vk", f"voice download failed: {response.status_code}")
    return response.content


def pending_done_buttons(events: Sequence[EventRead]) -> list[tuple[str, int]]:
    return [(f"Готово: {event.title}"[:40], event.id) for event in pending_events(events)]


async def send_reply(
    api: API,
    peer_id: int,
    user_id: int | str,
    response: AssistantResponse,
    tz: ZoneInfo,
) -> None:
    from vkbottle import Callback, Keyboard, KeyboardButtonColor
    from vkbottle.tools import VoiceMessageUploader

    text = response.text.strip()
    if text:
        await send_text(api, peer_id, text)
    if response.events:
        keyboard = Keyboard(one_time=False, inline=False)
        buttons = pending_done_buttons(response.events)
        if buttons:
            for label, event_id in buttons:
                keyboard.add(Callback(label, payload={"done": event_id}), color=KeyboardButtonColor.SECONDARY)
                keyboard.row()
        await send_text(
            api,
            peer_id,
            cards_text(response.events, tz, action_label(response.intent)),
            keyboard=keyboard.get_json() if buttons else None,
        )
    if response.audio:
        try:
            uploader = VoiceMessageUploader(api)
            attachment = await uploader.upload(response.audio, peer_id=peer_id)
            await api.messages.send(
                peer_id=peer_id,
                random_id=_random_id(),
                attachment=attachment,
            )
        except Exception:
            log.warning("vk: voice reply could not be uploaded", exc_info=True)


def _random_id() -> int:
    import secrets

    return secrets.randbelow(2**31 - 1)


async def send_text(api: API, peer_id: int, text: str, keyboard: str | None = None) -> None:
    await api.messages.send(
        peer_id=peer_id,
        random_id=_random_id(),
        message=text[:4000],
        keyboard=keyboard,
        dont_parse_links=1,
    )


def main_keyboard(settings: Settings) -> Any:
    from vkbottle import Keyboard, KeyboardButtonColor, OpenLink, Text

    keyboard = Keyboard(one_time=False, inline=False)
    for action in QUICK_ACTIONS:
        keyboard.add(Text(action), color=KeyboardButtonColor.PRIMARY)
        keyboard.row()
    keyboard.add(Text("Помощь"), color=KeyboardButtonColor.SECONDARY)
    keyboard.add(Text("Привязать аккаунт"), color=KeyboardButtonColor.SECONDARY)
    app_link = settings.mini_app_link(Platform.VK)
    if app_link:
        keyboard.row()
        keyboard.add(OpenLink("Открыть приложение", app_link), color=KeyboardButtonColor.PRIMARY)
    return keyboard.get_json()


def app_keyboard(settings: Settings) -> Any:
    from vkbottle import Keyboard, KeyboardButtonColor, OpenLink

    app_link = settings.mini_app_link(Platform.VK)
    if not app_link:
        return None
    keyboard = Keyboard(one_time=False, inline=False)
    keyboard.add(OpenLink("Открыть приложение", app_link), color=KeyboardButtonColor.PRIMARY)
    return keyboard.get_json()


async def handle_message(
    message: Message,
    api: API,
    assistant: AssistantService,
    settings: Settings,
    auth: AuthService | None,
) -> None:
    user_id = message.from_id
    peer_id = message.peer_id
    text = (message.text or "").strip()

    if text.lower() in {"/start", "начать", "start"}:
        await send_text(api, peer_id, GREETING, keyboard=main_keyboard(settings))
        return
    if text.lower() in {"/help", "помощь", "help"}:
        await send_text(api, peer_id, HELP, keyboard=main_keyboard(settings))
        return
    if text.lower() in {"/link", "привязать аккаунт"}:
        await _send_link_code(api, peer_id, user_id, message, auth, settings)
        return
    if text.lower() in {"/app", "приложение"}:
        app_link = settings.mini_app_link(Platform.VK)
        text_parts = [app_text(settings)]
        if app_link:
            text_parts.append(f"Мини-приложение ВКонтакте: {app_link}")
        await send_text(api, peer_id, "\n".join(text_parts), keyboard=app_keyboard(settings))
        return

    if text.startswith("/"):
        text = ""

    found = _find_audio(message.attachments)
    try:
        if found is not None:
            _, url = found
            audio = await download_voice(url)
            response = await assistant.handle_voice(Platform.VK, str(user_id), audio, source_format="ogg")
        elif text:
            response = await assistant.handle_text(Platform.VK, str(user_id), text)
        else:
            return
    except Exception:
        log.exception("vk: request failed for user %s", user_id)
        await send_text(api, peer_id, ERROR_REPLY)
        return
    await send_reply(api, peer_id, user_id, response, settings.tz)


async def _send_link_code(
    api: API,
    peer_id: int,
    user_id: int,
    message: Message,
    auth: AuthService | None,
    settings: Settings,
) -> None:
    if auth is None:
        await send_text(api, peer_id, "Привязка аккаунта недоступна.")
        return
    sender = getattr(message, "from_id", None)
    name = None
    identity = identity_for(Platform.VK, user_id, display_name_of(name))
    try:
        code = await auth.issue_link_code(identity)
    except Exception:
        log.exception("vk: link code request failed for user %s", sender or user_id)
        await send_text(api, peer_id, "Не удалось создать код привязки, попробуйте ещё раз.")
        return
    await send_text(api, peer_id, link_code_text(settings, code["code"]))


async def handle_callback_payload(
    payload: Any,
    api: API,
    assistant: AssistantService,
    user_id: int,
    peer_id: int,
    event_id: str | None = None,
) -> None:
    """Buttons on event cards carry the done action; answer them and confirm in chat."""
    event_id_value = _event_id_from_payload(payload)
    if event_id_value is None:
        return
    try:
        event = await assistant.set_event_status(Platform.VK, str(user_id), event_id_value, EventStatus.DONE)
    except Exception:
        log.warning("vk: event %s could not be completed", event_id_value, exc_info=True)
        return
    if event_id:
        try:
            await api.messages.send_message_event_answer(
                event_id=event_id,
                user_id=user_id,
                peer_id=peer_id,
                event_data='{"type":"show_snackbar","text":"Готово"}',
            )
        except Exception:
            log.debug("vk: callback acknowledgement failed", exc_info=True)
    await send_text(api, peer_id, f"Отметил «{event.title}» выполненным.")


def _event_id_from_payload(payload: Any) -> int | None:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("done")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
