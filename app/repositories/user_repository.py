from sqlalchemy import select

from app.db.models.user import User
from app.domain.enums import Platform
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_external_id(self, platform: Platform, external_id: str) -> User | None:
        statement = select(User).where(User.platform == platform, User.external_id == external_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        platform: Platform,
        external_id: str,
        username: str | None = None,
        timezone: str | None = None,
    ) -> User:
        user = await self.get_by_external_id(platform, external_id)
        if user is None:
            user = User(
                platform=platform,
                external_id=external_id,
                username=username,
                timezone=timezone or "Europe/Moscow",
            )
            return await self.add(user)

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
