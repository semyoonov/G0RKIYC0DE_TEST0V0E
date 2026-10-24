from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.user import _enum_values
from app.domain.enums import Platform

if TYPE_CHECKING:
    from app.db.models.user import User


class LinkCode(Base):
    """One-time code that attaches another platform identity to an existing account."""

    __tablename__ = "link_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform, native_enum=False, length=16, values_callable=_enum_values)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))

    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<LinkCode code={self.code} user={self.user_id} platform={self.platform}>"
