from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.timeutils import to_db, utcnow
from app.db.models.email_challenge import EmailChallenge
from app.db.models.user import User
from app.db.models.user_email import UserEmail
from app.domain.enums import Platform
from app.domain.identity import Identity
from app.repositories.account_repository import AccountRepository, LinkCodeError
from app.services.auth.email_sender import EmailDeliveryError, EmailSender
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
    "EmailAuthError",
    "EmailCodeRateLimit",
    "EmailDeliveryError",
    "Session",
    "SessionTokenError",
]


class EmailAuthError(ValueError):
    """The email or one-time verification code is invalid."""


class EmailCodeRateLimit(EmailAuthError):
    """A new code was requested too soon or too many times."""


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
        email_sender: EmailSender | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._clock = clock
        self._tokens = SessionTokens(settings.session_secret, settings.session_ttl_seconds)
        self._email_sender = email_sender or EmailSender(settings)

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
            raise LaunchError("ordinary web sessions require a verified email address")
        context = self.launch(platform, payload)
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
            if identity.platform is Platform.WEB:
                email_identity = await session.scalar(
                    select(UserEmail).where(UserEmail.web_identity_id == identity.external_id)
                )
                if email_identity is None:
                    raise SessionTokenError("web identity has no verified email")
            repository = AccountRepository(session)
            user = await repository.resolve(identity, self._settings.timezone)
            linked = tuple(await repository.identities(user))
        return self._session(LaunchContext(identity), user_id=user.id, linked=linked)

    async def request_email_code(self, email: str, identity: Identity | None = None) -> None:
        """Send a code to log in, or attach the verified email to an existing identity."""
        normalized = normalize_email(email)
        if not self._settings.email_code_secret.strip():
            raise EmailDeliveryError("EMAIL_CODE_SECRET is not configured")
        if not self._email_sender.configured:
            raise EmailDeliveryError("RESEND_API_KEY and EMAIL_FROM are not configured")

        moment = to_db(utcnow())
        identity_platform = identity.platform.value if identity else None
        identity_external_id = identity.external_id if identity else None
        code = f"{secrets.randbelow(1_000_000):06d}"
        code_hash = self._email_code_hash(normalized, code)

        async with self._session_factory() as session:
            latest = await session.scalar(
                select(EmailChallenge)
                .where(
                    EmailChallenge.email_normalized == normalized,
                    EmailChallenge.identity_platform == identity_platform,
                    EmailChallenge.identity_external_id == identity_external_id,
                )
                .order_by(EmailChallenge.created_at.desc())
                .limit(1)
            )
            if latest is not None:
                age_seconds = (moment - latest.created_at).total_seconds()
                if age_seconds < self._settings.email_code_cooldown_seconds:
                    raise EmailCodeRateLimit("Подождите немного перед повторной отправкой кода.")

            # Old codes from the same login flow cannot be used after a new request.
            previous = (
                await session.execute(
                    select(EmailChallenge).where(
                        EmailChallenge.email_normalized == normalized,
                        EmailChallenge.identity_platform == identity_platform,
                        EmailChallenge.identity_external_id == identity_external_id,
                        EmailChallenge.used_at.is_(None),
                    )
                )
            ).scalars().all()
            for row in previous:
                row.used_at = moment

            challenge = EmailChallenge(
                email_normalized=normalized,
                code_hash=code_hash,
                identity_platform=identity_platform,
                identity_external_id=identity_external_id,
                created_at=moment,
                expires_at=moment + timedelta(seconds=self._settings.email_code_ttl_seconds),
                attempts=0,
            )
            session.add(challenge)
            await session.commit()
            challenge_id = challenge.id

        try:
            await self._email_sender.send_login_code(normalized, code)
        except EmailDeliveryError:
            async with self._session_factory() as session:
                challenge = await session.get(EmailChallenge, challenge_id)
                if challenge is not None:
                    challenge.used_at = to_db(utcnow())
                    await session.commit()
            raise

    async def verify_email_code(
        self,
        email: str,
        code: str,
        identity: Identity | None = None,
    ) -> Session:
        """Verify an email code and return a web session for the resolved account."""
        normalized = normalize_email(email)
        supplied_code = code.strip()
        if not re.fullmatch(r"\d{6}", supplied_code):
            raise EmailAuthError("Код должен состоять из шести цифр.")
        moment = to_db(utcnow())
        identity_platform = identity.platform.value if identity else None
        identity_external_id = identity.external_id if identity else None

        async with self._session_factory() as session:
            challenge = await session.scalar(
                select(EmailChallenge)
                .where(
                    EmailChallenge.email_normalized == normalized,
                    EmailChallenge.identity_platform == identity_platform,
                    EmailChallenge.identity_external_id == identity_external_id,
                    EmailChallenge.used_at.is_(None),
                )
                .order_by(EmailChallenge.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            if challenge is None:
                raise EmailAuthError("Код не найден или уже использован. Запросите новый код.")
            if challenge.expires_at <= moment:
                challenge.used_at = moment
                await session.commit()
                raise EmailAuthError("Срок действия кода истёк. Запросите новый код.")
            expected_hash = self._email_code_hash(normalized, supplied_code)
            if not hmac.compare_digest(challenge.code_hash, expected_hash):
                challenge.attempts += 1
                if challenge.attempts >= self._settings.email_code_max_attempts:
                    challenge.used_at = moment
                await session.commit()
                raise EmailAuthError("Неверный код. Проверьте письмо и попробуйте ещё раз.")

            repository = AccountRepository(session)
            email_row = await session.scalar(
                select(UserEmail).where(UserEmail.email_normalized == normalized)
            )

            if identity is not None:
                # A client is explicitly linking itself to the verified email. If
                # the email is new, keep the client's existing account and history.
                current_user = await repository.resolve(identity, self._settings.timezone, commit=False)
                if email_row is None:
                    user = current_user
                    web_identity_id = self._new_web_identity_id()
                    email_row = UserEmail(
                        user_id=user.id,
                        email_normalized=normalized,
                        web_identity_id=web_identity_id,
                        verified_at=moment,
                        created_at=moment,
                    )
                    session.add(email_row)
                    await session.flush()
                else:
                    owner = await session.get(User, email_row.user_id)
                    if owner is None:
                        raise EmailAuthError("Не удалось найти аккаунт для этого email.")
                    if owner.id != current_user.id:
                        user = await repository.attach(owner, identity, commit=False)
                    else:
                        user = owner
                    web_identity_id = email_row.web_identity_id
            else:
                # A normal browser login: use the account assigned to this email,
                # or create a new account only after the code has been verified.
                if email_row is None:
                    web_identity_id = self._new_web_identity_id()
                    user = User(
                        platform=Platform.WEB,
                        external_id=web_identity_id,
                        username=None,
                        timezone=self._settings.timezone,
                    )
                    session.add(user)
                    await session.flush()
                    email_row = UserEmail(
                        user_id=user.id,
                        email_normalized=normalized,
                        web_identity_id=web_identity_id,
                        verified_at=moment,
                        created_at=moment,
                    )
                    session.add(email_row)
                else:
                    user = await session.get(User, email_row.user_id)
                    if user is None:
                        raise EmailAuthError("Не удалось найти аккаунт для этого email.")
                    web_identity_id = email_row.web_identity_id

            # Every verified email has a stable WEB identity. It is the primary
            # identity for browser-only users, or an AccountLink for bot-first users.
            await repository.attach(user, Identity(Platform.WEB, web_identity_id), commit=False)
            challenge.used_at = moment
            await session.commit()
            await session.refresh(user)
            linked = tuple(await repository.identities(user))

        web_identity = Identity(Platform.WEB, web_identity_id)
        return self._session(
            LaunchContext(web_identity),
            user_id=user.id,
            linked=linked,
        )

    def _email_code_hash(self, email: str, code: str) -> str:
        secret = self._settings.email_code_secret.encode("utf-8")
        message = f"{email}:{code}".encode("utf-8")
        return hmac.new(secret, message, hashlib.sha256).hexdigest()

    @staticmethod
    def _new_web_identity_id() -> str:
        return "email-" + secrets.token_urlsafe(24)

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


async def _redeem(repository: AccountRepository, code: str):
    """Attach the start-app code when it is a valid link code; ignore anything else."""
    try:
        return await repository.redeem_code(code)
    except LinkCodeError:
        return None
