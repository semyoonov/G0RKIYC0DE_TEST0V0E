from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.account_link import AccountLink
from app.db.models.user import User
from app.domain.enums import Platform
from app.repositories.base import BaseRepository


CreatedHook = Callable[[AsyncSession, User], Awaitable[None]]


class UserRepository(BaseRepository[User]):
    model = User

    def __init__(self, session: AsyncSession, *, on_created: CreatedHook | None = None) -> None:
        super().__init__(session)
        self._on_created = on_created

    async def get_by_external_id(self, platform: Platform, external_id: str) -> User | None:
        statement = select(User).where(User.platform == platform, User.external_id == external_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def resolve(self, platform: Platform, external_id: str) -> User | None:
        """The account behind an identity: its own row, or the account it was linked to."""
        user = await self.get_by_external_id(platform, external_id)
        if user is not None:
            return user
        result = await self.session.execute(
            select(AccountLink).where(
                AccountLink.platform == platform,
                AccountLink.external_id == external_id,
            )
        )
        link = result.scalar_one_or_none()
        if link is None:
            return None
        return await self.session.get(User, link.user_id)

    async def get_or_create(
        self,
        platform: Platform,
        external_id: str,
        username: str | None = None,
        timezone: str | None = None,
    ) -> User:
        user = await self.resolve(platform, external_id)
        if user is None:
            user = User(
                platform=platform,
                external_id=external_id,
                username=username,
                timezone=timezone or "Europe/Moscow",
            )
            self.session.add(user)
            await self.session.flush()
            if self._on_created is not None:
                await self._on_created(self.session, user)
            await self.session.commit()
            await self.session.refresh(user)
            return user

        changed = False
        if username and user.username != username:
            user.username = username
            changed = True
        if timezone and user.timezone != timezone:
            user.timezone = timezone
            changed = True
        if changed:
            await self.session.commit()
            await self.session.refresh(user)
        return user
