from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.user import _enum_values
from app.domain.enums import Platform

if TYPE_CHECKING:
    from app.db.models.user import User


class AccountLink(Base):
    """An extra platform identity that belongs to an account owned by a `users` row."""

    __tablename__ = "account_links"
    __table_args__ = (UniqueConstraint("platform", "external_id", name="uq_account_links_identity"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform, native_enum=False, length=16, values_callable=_enum_values)
    )
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="links")

    def __repr__(self) -> str:
        return f"<AccountLink user={self.user_id} platform={self.platform} external_id={self.external_id}>"
