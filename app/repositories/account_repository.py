from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update

from app.core.timeutils import to_db, utcnow
from app.db.models.account_link import AccountLink
from app.db.models.event import Event
from app.db.models.user_email import UserEmail
from app.db.models.link_code import LinkCode
from app.db.models.user import User
from app.domain.enums import Platform
from app.domain.identity import Identity
from app.repositories.base import BaseRepository

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
DEFAULT_CODE_TTL_SECONDS = 15 * 60


class LinkCodeError(ValueError):
    """The code is unknown, already used or expired."""


class AccountRepository(BaseRepository[User]):
    """Resolves platform identities to the account row that owns the events."""

    model = User

    async def resolve(
        self,
        identity: Identity,
        timezone: str | None = None,
        *,
        commit: bool = True,
    ) -> User:
        """Find or create the owner of an identity.

        Set commit=False when this lookup is part of a larger transaction, such as
        verifying an email code and merging accounts atomically.
        """
        user = await self._by_identity(identity.platform, identity.external_id)
        if user is not None:
            await self._touch(user, identity.display_name, commit=commit)
            return user

        link = await self._link_for(identity.platform, identity.external_id)
        if link is not None:
            owner = await self.session.get(User, link.user_id)
            if owner is not None:
                await self._touch(owner, identity.display_name, commit=commit)
                return owner

        user = User(
            platform=identity.platform,
            external_id=identity.external_id,
            username=identity.display_name,
            timezone=timezone or "Europe/Moscow",
        )
        self.session.add(user)
        if commit:
            await self.session.commit()
            await self.session.refresh(user)
        else:
            await self.session.flush()
        return user

    async def identities(self, user: User) -> list[Identity]:
        rows = await self.session.execute(select(AccountLink).where(AccountLink.user_id == user.id))
        linked = [
            Identity(platform=row.platform, external_id=row.external_id)
            for row in rows.scalars().all()
        ]
        primary = Identity(platform=user.platform, external_id=user.external_id, display_name=user.username)
        unique: dict[tuple[Platform, str], Identity] = {(primary.platform, primary.external_id): primary}
        for identity in linked:
            unique.setdefault((identity.platform, identity.external_id), identity)
        return list(unique.values())

    async def attach(self, target: User, identity: Identity, *, commit: bool = True) -> User:
        """Bind an identity to target, merging the identity's entire old account if needed.

        The merge moves events, email identities and all other platform links. `commit=False`
        lets a higher-level service combine this operation with a verification-code update.
        """
        target_primary = (target.platform, target.external_id)
        identity_key = (identity.platform, identity.external_id)
        if identity_key == target_primary:
            return target

        source = await self._owner_for_identity(identity)
        if source is not None and source.id != target.id:
            await self._merge_users(source, target)

        link = await self._link_for(identity.platform, identity.external_id)
        if link is None:
            self.session.add(
                AccountLink(
                    user_id=target.id,
                    platform=identity.platform,
                    external_id=identity.external_id,
                )
            )
        elif link.user_id != target.id:
            link.user_id = target.id

        if commit:
            await self.session.commit()
            await self.session.refresh(target)
        else:
            await self.session.flush()
        return target

    async def _owner_for_identity(self, identity: Identity) -> User | None:
        """Find the account that currently owns an identity, primary or linked."""
        owner = await self._by_identity(identity.platform, identity.external_id)
        if owner is not None:
            return owner
        link = await self._link_for(identity.platform, identity.external_id)
        if link is None:
            return None
        return await self.session.get(User, link.user_id)

    async def _merge_users(self, source: User, target: User) -> None:
        """Move all data and identities from source to target in the current transaction."""
        await self.session.execute(
            update(Event).where(Event.user_id == source.id).values(user_id=target.id)
        )
        # If a source account had already been email-authenticated, keep its email
        # address too. UserEmail rows are account aliases, not owned by a platform.
        await self.session.execute(
            update(UserEmail).where(UserEmail.user_id == source.id).values(user_id=target.id)
        )

        target_primary = (target.platform, target.external_id)
        target_links = (
            await self.session.execute(select(AccountLink).where(AccountLink.user_id == target.id))
        ).scalars().all()
        known = {(row.platform, row.external_id) for row in target_links}
        source_links = (
            await self.session.execute(select(AccountLink).where(AccountLink.user_id == source.id))
        ).scalars().all()

        for row in source_links:
            key = (row.platform, row.external_id)
            if key == target_primary or key in known:
                await self.session.delete(row)
            else:
                row.user_id = target.id
                known.add(key)

        source_primary = (source.platform, source.external_id)
        if source_primary != target_primary and source_primary not in known:
            self.session.add(
                AccountLink(
                    user_id=target.id,
                    platform=source.platform,
                    external_id=source.external_id,
                )
            )
            known.add(source_primary)

        await self.session.delete(source)
        await self.session.flush()

    async def issue_code(
        self,
        user: User,
        platform: Platform,
        ttl_seconds: int = DEFAULT_CODE_TTL_SECONDS,
        *,
        now: datetime | None = None,
    ) -> LinkCode:
        moment = now or to_db(utcnow())
        for _ in range(8):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if await self.find_code(code) is None:
                break
        else:  # pragma: no cover - six characters of a 32-letter alphabet never collide eight times
            raise LinkCodeError("cannot allocate a unique link code")
        row = LinkCode(
            code=code,
            user_id=user.id,
            platform=platform,
            expires_at=moment + timedelta(seconds=ttl_seconds),
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def find_code(self, code: str) -> LinkCode | None:
        normalized = code.strip().upper()
        if not normalized:
            return None
        result = await self.session.execute(select(LinkCode).where(LinkCode.code == normalized))
        return result.scalar_one_or_none()

    async def redeem_code(self, code: str, *, now: datetime | None = None) -> User:
        row = await self.find_code(code)
        moment = now or to_db(utcnow())
        if row is None:
            raise LinkCodeError("код не найден")
        if row.used_at is not None:
            raise LinkCodeError("код уже использован")
        if row.expires_at <= moment:
            raise LinkCodeError("срок действия кода истёк")
        owner = await self.session.get(User, row.user_id)
        if owner is None:
            raise LinkCodeError("аккаунт кода не найден")
        row.used_at = moment
        await self.session.commit()
        return owner

    async def _by_identity(self, platform: Platform, external_id: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.platform == platform, User.external_id == external_id)
        )
        return result.scalar_one_or_none()

    async def _link_for(self, platform: Platform, external_id: str) -> AccountLink | None:
        result = await self.session.execute(
            select(AccountLink).where(
                AccountLink.platform == platform,
                AccountLink.external_id == external_id,
            )
        )
        return result.scalar_one_or_none()

    async def _touch(self, user: User, display_name: str | None, *, commit: bool = True) -> None:
        if not display_name or user.username == display_name:
            return
        user.username = display_name
        if commit:
            await self.session.commit()
        else:
            await self.session.flush()
