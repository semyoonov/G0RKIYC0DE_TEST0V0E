from __future__ import annotations

import httpx

from app.core.logger import get_logger

log = get_logger(__name__)

VK_API_URL = "https://api.vk.com/method/users.get"
VK_API_VERSION = "5.199"
_TIMEOUT_SECONDS = 5.0


async def fetch_display_name(access_token: str, user_id: str) -> str | None:
    """VK launch parameters carry only the numeric id; the service token adds a human name."""
    if not access_token.strip() or not user_id.strip():
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                VK_API_URL,
                data={
                    "access_token": access_token.strip(),
                    "user_ids": user_id.strip(),
                    "v": VK_API_VERSION,
                    "lang": "ru",
                },
            )
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        log.warning("vk: profile lookup failed for user %s", user_id, exc_info=True)
        return None
    items = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        return None
    item = items[0] if isinstance(items[0], dict) else {}
    name = " ".join(
        part.strip()
        for part in (item.get("first_name"), item.get("last_name"))
        if isinstance(part, str) and part.strip()
    )
    return name or None
