from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EmailChallenge(Base):
    """Short-lived, single-use email verification code."""

    __tablename__ = "email_challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_normalized: Mapped[str] = mapped_column(String(254), index=True, nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Null identity means a normal browser login. Otherwise the verified email
    # is being attached to a currently authenticated platform identity.
    identity_platform: Mapped[str | None] = mapped_column(String(16), nullable=True)
    identity_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<EmailChallenge email={self.email_normalized!r} used={self.used_at is not None}>"
