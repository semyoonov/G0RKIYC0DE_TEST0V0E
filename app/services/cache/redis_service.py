import json
import time
from collections import deque
from typing import Any

from redis.asyncio import Redis

from app.core.logger import get_logger

log = get_logger(__name__)


class CacheService:
    """JSON-кеш с историей диалога.

    Когда Redis недоступен, переходит на память процесса — так локальный демо-режим
    работает без контейнера; о каждом сбое Redis пишется одно предупреждение, дальше он
    игнорируется.
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        *,
        enabled: bool = True,
        ttl_seconds: int = 60,
        client: Redis | None = None,
        history_limit: int = 200,
    ) -> None:
        self._url = url
        self._enabled = enabled
        self._ttl_seconds = ttl_seconds
        self._client = client
        self._client_ready = client is not None
        self._redis_failed = False
        self._memory: dict[str, tuple[float, str]] = {}
        self._history: dict[str, deque[str]] = {}
        self._history_limit = history_limit

    @property
    def available(self) -> bool:
        return self._enabled and not self._redis_failed

    async def _get_client(self) -> Redis | None:
        if not self._enabled or self._redis_failed:
            return None
        if self._client_ready:
            return self._client
        try:
            client = Redis.from_url(self._url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
            await client.ping()
        except Exception as error:  # noqa: BLE001 - any driver or network error disables Redis
            self._redis_failed = True
            log.warning("redis is unavailable, using in-memory cache: %s", error)
            return None
        self._client = client
        self._client_ready = True
        return client

    async def get_json(self, key: str) -> Any | None:
        client = await self._get_client()
        if client is not None:
            try:
                raw = await client.get(key)
            except Exception as error:  # noqa: BLE001
                self._disable(error)
                return self._memory_get(key)
            return json.loads(raw) if raw else None
        return self._memory_get(key)

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl_seconds
        payload = json.dumps(value, ensure_ascii=False, default=str)
        client = await self._get_client()
        if client is not None:
            try:
                await client.set(key, payload, ex=ttl)
                return
            except Exception as error:  # noqa: BLE001
                self._disable(error)
        self._memory[key] = (time.monotonic() + ttl, payload)

    async def delete(self, key: str) -> None:
        self._memory.pop(key, None)
        client = await self._get_client()
        if client is not None:
            try:
                await client.delete(key)
            except Exception as error:  # noqa: BLE001
                self._disable(error)

    async def delete_prefix(self, prefix: str) -> None:
        self._memory = {key: value for key, value in self._memory.items() if not key.startswith(prefix)}
        client = await self._get_client()
        if client is None:
            return
        try:
            async for key in client.scan_iter(match=f"{prefix}*", count=200):
                await client.delete(key)
        except Exception as error:  # noqa: BLE001
            self._disable(error)

    async def push_history(self, key: str, entry: dict[str, Any], limit: int) -> None:
        payload = json.dumps(entry, ensure_ascii=False)
        client = await self._get_client()
        if client is not None:
            try:
                await client.rpush(key, payload)
                await client.ltrim(key, -limit, -1)
                await client.expire(key, 24 * 60 * 60)
                return
            except Exception as error:  # noqa: BLE001
                self._disable(error)
        bucket = self._history.setdefault(key, deque(maxlen=min(limit, self._history_limit)))
        bucket.append(payload)

    async def get_history(self, key: str, limit: int) -> list[dict[str, Any]]:
        client = await self._get_client()
        if client is not None:
            try:
                raw_items = await client.lrange(key, -limit, -1)
            except Exception as error:  # noqa: BLE001
                self._disable(error)
                raw_items = list(self._history.get(key, ()))[-limit:]
        else:
            raw_items = list(self._history.get(key, ()))[-limit:]
        return [json.loads(item) for item in raw_items]

    async def close(self) -> None:
        if self._client is not None and not self._redis_failed:
            try:
                await self._client.aclose()
            except Exception:  # noqa: BLE001 - shutdown must not fail on cache cleanup
                pass

    def _disable(self, error: Exception) -> None:
        if not self._redis_failed:
            log.warning("redis call failed, switching to in-memory cache: %s", error)
        self._redis_failed = True

    def _memory_get(self, key: str) -> Any | None:
        cached = self._memory.get(key)
        if cached is None:
            return None
        expires_at, payload = cached
        if expires_at < time.monotonic():
            self._memory.pop(key, None)
            return None
        return json.loads(payload)
