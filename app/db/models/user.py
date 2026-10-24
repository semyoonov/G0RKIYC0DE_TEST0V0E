from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.domain.enums import Platform

if TYPE_CHECKING:
    from app.db.models.account_link import AccountLink
    from app.db.models.event import Event


def _enum_values(enum_cls: type) -> list[str]:
    return [member.value for member in enum_cls]


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_users_platform_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform, native_enum=False, length=16, values_callable=_enum_values)
    )
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    events: Mapped[list["Event"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    links: Mapped[list["AccountLink"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} platform={self.platform} external_id={self.external_id}>"
