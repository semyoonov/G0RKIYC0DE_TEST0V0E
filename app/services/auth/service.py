from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.timeutils import to_db, utcnow
from app.db.models.user import User
from app.db.models.user_email import UserEmail
from app.domain.enums import Platform
from app.domain.identity import Identity
from app.repositories.account_repository import AccountRepository
from app.services.auth.launch import (
    LaunchContext,
    LaunchError,
    LaunchNotConfigured,
    max_identity,
    telegram_identity,
    vk_identity,
)
from app.services.auth.passwords import PasswordError, hash_password, verify_password
from app.services.auth.tokens import SessionTokenError, SessionTokens
from app.services.auth.vk_profile import fetch_display_name
from app.services.demo_seed import seed_demo_events

__all__ = [
    "AuthService",
    "CredentialsError",
    "EmailAuthError",
    "LaunchError",
    "LaunchNotConfigured",
    "PasswordError",
    "Session",
    "SessionTokenError",
]


class EmailAuthError(ValueError):
    """The email address cannot be used for this account."""


class CredentialsError(EmailAuthError):
    """The email and password pair do not match a registered account."""


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")


def normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 254 or not _EMAIL_RE.fullmatch(normalized):
        raise EmailAuthError("Введите корректный адрес электронной почты.")
    return normalized


@dataclass(frozen=True, slots=True)
class Session:
    """The outcome of a successful login: who the visitor is and their account."""

    identity: Identity
    user_id: int
    token: str
    linked: tuple[Identity, ...]
    email: str | None = None
    has_password: bool = False

    def as_dict(self, *, links: dict[str, str | None] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "token": self.token,
            "identity": self.identity.as_dict(),
            "user": {"id": self.user_id},
            "linked": [identity.as_dict() for identity in self.linked],
            "email": self.email,
            "has_password": self.has_password,
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

    def _accounts(self, session: AsyncSession) -> AccountRepository:
        """Repository that fills a new account with sample plans when seeding is on."""
        hook = self._seed_demo_events if self._settings.demo_seed_enabled else None
        return AccountRepository(session, on_created=hook)

    async def _seed_demo_events(self, session: AsyncSession, user: User) -> None:
        await seed_demo_events(session, user, self._settings.timezone)

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
    ) -> Session:
        if platform is Platform.WEB:
            raise LaunchError("a browser starts a guest session or logs in with a password")
        context = self.launch(platform, payload)
        if platform is Platform.VK and not context.identity.display_name:
            name = await fetch_display_name(self._settings.vk_access_token, context.identity.external_id)
            if name:
                context = replace(context, identity=replace(context.identity, display_name=name))
        async with self._session_factory() as session:
            repository = self._accounts(session)
            user = await repository.resolve(context.identity, self._settings.timezone)
            linked = tuple(await repository.identities(user))
            email = await _email_of(session, user.id)
        return self._session(context, user_id=user.id, linked=linked, email=email)

    async def open_guest_session(self) -> Session:
        """Start an anonymous browser account, so the app works without a login prompt."""
        identity = Identity(Platform.WEB, "guest-" + secrets.token_urlsafe(18))
        async with self._session_factory() as session:
            repository = self._accounts(session)
            user = await repository.resolve(identity, self._settings.timezone)
            linked = tuple(await repository.identities(user))
        return self._session(LaunchContext(identity), user_id=user.id, linked=linked)

    async def account(self, token: str | None) -> Session:
        identity = self._tokens.parse(token, now=self._clock())
        async with self._session_factory() as session:
            repository = self._accounts(session)
            user = await repository.resolve(identity, self._settings.timezone)
            linked = tuple(await repository.identities(user))
            email_row = await _email_row(session, user.id)
        return self._session(
            LaunchContext(identity),
            user_id=user.id,
            linked=linked,
            email=email_row.email_normalized if email_row else None,
            has_password=bool(email_row and email_row.password_hash),
        )

    async def register(
        self,
        email: str,
        password: str,
        identity: Identity | None = None,
    ) -> Session:
        """Create an email login, keeping the events of the identity that asks for it.

        A bot or mini-app account has no email; registering from inside it attaches
        the address to that same account, so the web version opens the same tasks.
        """
        normalized = normalize_email(email)
        password_hash = hash_password(password)
        moment = to_db(utcnow())
        async with self._session_factory() as session:
            repository = self._accounts(session)
            email_row = await session.scalar(
                select(UserEmail).where(UserEmail.email_normalized == normalized)
            )
            if email_row is not None:
                user, email_row = await self._claim_existing(repository, session, email_row, identity)
                email_row.password_hash = password_hash
                web_identity_id = email_row.web_identity_id
            else:
                web_identity_id = self._new_web_identity_id()
                user = await self._account_for(repository, session, identity, web_identity_id)
                session.add(
                    UserEmail(
                        user_id=user.id,
                        email_normalized=normalized,
                        web_identity_id=web_identity_id,
                        password_hash=password_hash,
                        claimed_at=moment,
                    )
                )
            await repository.attach(user, Identity(Platform.WEB, web_identity_id), commit=False)
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise EmailAuthError("Этот адрес уже зарегистрирован. Войдите с паролем.") from error
            await session.refresh(user)
            linked = tuple(await repository.identities(user))
        return self._session(
            LaunchContext(identity or Identity(Platform.WEB, web_identity_id)),
            user_id=user.id,
            linked=linked,
            email=normalized,
            has_password=True,
        )

    async def login(
        self,
        email: str,
        password: str,
        identity: Identity | None = None,
    ) -> Session:
        """Sign in with a password and bind the current platform identity to the account."""
        normalized = normalize_email(email)
        async with self._session_factory() as session:
            repository = self._accounts(session)
            email_row = await session.scalar(
                select(UserEmail).where(UserEmail.email_normalized == normalized)
            )
            if email_row is None or not verify_password(password, email_row.password_hash):
                raise CredentialsError("Неверный адрес электронной почты или пароль.")
            owner = await session.get(User, email_row.user_id)
            if owner is None:
                raise EmailAuthError("Не удалось найти аккаунт для этого адреса.")
            user = owner if identity is None else await repository.attach(owner, identity, commit=False)
            web_identity_id = email_row.web_identity_id
            await repository.attach(user, Identity(Platform.WEB, web_identity_id), commit=False)
            await session.commit()
            await session.refresh(user)
            linked = tuple(await repository.identities(user))
        return self._session(
            LaunchContext(identity or Identity(Platform.WEB, web_identity_id)),
            user_id=user.id,
            linked=linked,
            email=normalized,
            has_password=True,
        )

    async def _account_for(
        self,
        repository: AccountRepository,
        session: AsyncSession,
        identity: Identity | None,
        web_identity_id: str,
    ) -> User:
        """The account that will own the new email: the caller's own, or a fresh one."""
        if identity is not None:
            return await repository.resolve(identity, self._settings.timezone, commit=False)
        user = User(
            platform=Platform.WEB,
            external_id=web_identity_id,
            username=None,
            timezone=self._settings.timezone,
        )
        session.add(user)
        await session.flush()
        return user

    async def _claim_existing(
        self,
        repository: AccountRepository,
        session: AsyncSession,
        email_row: UserEmail,
        identity: Identity | None,
    ) -> tuple[User, UserEmail]:
        """Claim an email left over from the removed code login.

        Only the account that already holds the address can take it over: the old
        flow verified ownership, and this one must not hand it to a stranger.
        """
        if email_row.password_hash:
            raise EmailAuthError("Этот адрес уже зарегистрирован. Войдите с паролем.")
        owner = await session.get(User, email_row.user_id)
        if owner is None:
            raise EmailAuthError("Не удалось найти аккаунт для этого адреса.")
        if identity is None:
            raise EmailAuthError("Этот адрес привязан к другому аккаунту. Войдите из него.")
        current = await repository.resolve(identity, self._settings.timezone, commit=False)
        if current.id != owner.id:
            raise EmailAuthError("Этот адрес привязан к другому аккаунту. Войдите из него.")
        return owner, email_row

    @staticmethod
    def _new_web_identity_id() -> str:
        return "email-" + secrets.token_urlsafe(24)

    def _session(
        self,
        context: LaunchContext,
        *,
        user_id: int,
        linked: tuple[Identity, ...],
        email: str | None = None,
        has_password: bool = False,
    ) -> Session:
        return Session(
            identity=context.identity,
            user_id=user_id,
            token=self._tokens.issue(context.identity, now=self._clock()),
            linked=linked,
            email=email,
            has_password=has_password,
        )


async def _email_row(session: AsyncSession, user_id: int) -> UserEmail | None:
    return await session.scalar(
        select(UserEmail).where(UserEmail.user_id == user_id).order_by(UserEmail.id).limit(1)
    )


async def _email_of(session: AsyncSession, user_id: int) -> str | None:
    row = await _email_row(session, user_id)
    return row.email_normalized if row and row.password_hash else None
