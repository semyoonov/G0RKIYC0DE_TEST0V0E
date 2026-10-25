from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.enums import Platform
from app.domain.identity import Identity
from app.repositories.account_repository import AccountRepository, LinkCodeError
from app.services.auth.launch import (
    LaunchContext,
    LaunchError,
    LaunchNotConfigured,
    max_identity,
    telegram_identity,
    vk_identity,
)
from app.services.auth.tokens import SessionTokenError, SessionTokens
from app.services.auth.vk_profile import fetch_display_name

__all__ = [
    "AuthService",
    "LaunchError",
    "LaunchNotConfigured",
    "LinkCodeError",
    "Session",
    "SessionTokenError",
]


@dataclass(frozen=True, slots=True)
class Session:
    """The outcome of a successful login: who the visitor is and their account."""

    identity: Identity
    user_id: int
    token: str
    linked: tuple[Identity, ...]
    start_param: str | None = None
    link_redeemed: bool = False

    def as_dict(self, *, links: dict[str, str | None] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "token": self.token,
            "identity": self.identity.as_dict(),
            "user": {"id": self.user_id},
            "linked": [identity.as_dict() for identity in self.linked],
            "start_param": self.start_param,
            "link_redeemed": self.link_redeemed,
        }
        if links is not None:
            payload["mini_apps"] = links
        return payload


class AuthService:
    """Turns a platform launch into an account, and links accounts across platforms."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._clock = clock
        self._tokens = SessionTokens(settings.session_secret, settings.session_ttl_seconds)

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def tokens(self) -> SessionTokens:
        return self._tokens

    def launch(self, platform: Platform, payload: str | None) -> LaunchContext:
        """Validate platform launch data; raises LaunchError when it cannot be trusted."""
        now = int(self._clock())
        if platform is Platform.TELEGRAM:
            return telegram_identity(payload, self._settings.telegram_bot_token, now=now)
        if platform is Platform.MAX:
            return max_identity(payload, self._settings.max_bot_token, now=now)
        if platform is Platform.VK:
            return vk_identity(
                payload,
                self._settings.vk_mini_app_secret,
                app_id=self._settings.vk_mini_app_id or None,
                now=now,
            )
        raise LaunchError(f"platform {platform.value} has no launch parameters")

    async def open_session(
        self,
        platform: Platform,
        payload: str | None = None,
        client_id: str | None = None,
    ) -> Session:
        context = (
            LaunchContext(Identity(Platform.WEB, _web_client_id(client_id)))
            if platform is Platform.WEB
            else self.launch(platform, payload)
        )
        if platform is Platform.VK and not context.identity.display_name:
            name = await fetch_display_name(self._settings.vk_access_token, context.identity.external_id)
            if name:
                context = replace(context, identity=replace(context.identity, display_name=name))
        redeemed = False
        async with self._session_factory() as session:
            repository = AccountRepository(session)
            user = await repository.resolve(context.identity, self._settings.timezone)
            if context.start_param:
                owner = await _redeem(repository, context.start_param)
                if owner is not None and owner.id != user.id:
                    user = await repository.attach(owner, context.identity)
                    redeemed = True
            linked = tuple(await repository.identities(user))
        return self._session(context, user_id=user.id, linked=linked, redeemed=redeemed)

    async def account(self, token: str | None) -> Session:
        identity = self._tokens.parse(token, now=self._clock())
        async with self._session_factory() as session:
            repository = AccountRepository(session)
            user = await repository.resolve(identity, self._settings.timezone)
            linked = tuple(await repository.identities(user))
        return self._session(
            LaunchContext(identity),
            user_id=user.id,
            linked=linked,
        )

    async def issue_link_code(self, identity: Identity) -> dict[str, Any]:
        async with self._session_factory() as session:
            repository = AccountRepository(session)
            user = await repository.resolve(identity, self._settings.timezone)
            row = await repository.issue_code(user, identity.platform, self._settings.link_code_ttl_seconds)
        links = self._settings.mini_app_links(row.code)
        return {
            "code": row.code,
            "expires_at": row.expires_at.isoformat() + "Z",
            "expires_in": self._settings.link_code_ttl_seconds,
            "platform": identity.platform.value,
            "mini_apps": links,
            "web_link": self._settings.mini_app_link(Platform.WEB, row.code),
        }

    async def redeem(self, identity: Identity, code: str) -> Session:
        async with self._session_factory() as session:
            repository = AccountRepository(session)
            owner = await repository.redeem_code(code)
            user = await repository.attach(owner, identity)
            linked = tuple(await repository.identities(user))
        return self._session(LaunchContext(identity), user_id=user.id, linked=linked, redeemed=True)

    def _session(
        self,
        context: LaunchContext,
        *,
        user_id: int,
        linked: tuple[Identity, ...],
        redeemed: bool = False,
    ) -> Session:
        return Session(
            identity=context.identity,
            user_id=user_id,
            token=self._tokens.issue(context.identity, now=self._clock()),
            linked=linked,
            start_param=context.start_param,
            link_redeemed=redeemed,
        )


def _web_client_id(client_id: str | None) -> str:
    value = (client_id or "").strip()
    if value:
        return value[:128]
    return f"web-{secrets.token_hex(8)}"


async def _redeem(repository: AccountRepository, code: str):
    """Attach the start-app code when it is a valid link code; ignore anything else."""
    try:
        return await repository.redeem_code(code)
    except LinkCodeError:
        return None
