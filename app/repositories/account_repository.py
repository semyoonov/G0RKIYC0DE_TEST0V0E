from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update

from app.core.timeutils import to_db, utcnow
from app.db.models.account_link import AccountLink
from app.db.models.event import Event
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

    async def resolve(self, identity: Identity, timezone: str | None = None) -> User:
        user = await self._by_identity(identity.platform, identity.external_id)
        if user is not None:
            await self._touch(user, identity.display_name)
            return user

        link = await self._link_for(identity.platform, identity.external_id)
        if link is not None:
            owner = await self.session.get(User, link.user_id)
            if owner is not None:
                await self._touch(owner, identity.display_name)
                return owner

        user = User(
            platform=identity.platform,
            external_id=identity.external_id,
            username=identity.display_name,
            timezone=timezone or "Europe/Moscow",
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
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

    async def attach(self, target: User, identity: Identity) -> User:
        """Bind `identity` to `target`, folding any history the identity already had."""
        if identity.platform is target.platform and identity.external_id == target.external_id:
            return target

        current = await self._by_identity(identity.platform, identity.external_id)
        if current is not None and current.id != target.id:
            await self.session.execute(
                update(Event).where(Event.user_id == current.id).values(user_id=target.id)
            )
            existing_links = (
                await self.session.execute(
                    select(AccountLink).where(AccountLink.user_id == current.id)
                )
            ).scalars().all()
            for existing_link in existing_links:
                if existing_link.platform is target.platform and existing_link.external_id == target.external_id:
                    await self.session.delete(existing_link)
                else:
                    existing_link.user_id = target.id
            await self.session.delete(current)

        link = await self._link_for(identity.platform, identity.external_id)
        if link is None:
            self.session.add(
                AccountLink(
                    user_id=target.id,
                    platform=identity.platform,
                    external_id=identity.external_id,
                )
            )
        else:
            link.user_id = target.id
        await self.session.commit()
        await self.session.refresh(target)
        return target

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

    async def _touch(self, user: User, display_name: str | None) -> None:
        if not display_name or user.username == display_name:
            return
        user.username = display_name
        await self.session.commit()
