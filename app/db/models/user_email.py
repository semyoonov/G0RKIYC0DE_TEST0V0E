from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserEmail(Base):
    """A verified email address and the stable web identity used for sessions."""

    __tablename__ = "user_emails"
    __table_args__ = (
        UniqueConstraint("email_normalized", name="uq_user_emails_email_normalized"),
        UniqueConstraint("web_identity_id", name="uq_user_emails_web_identity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email_normalized: Mapped[str] = mapped_column(String(254), nullable=False)
    web_identity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())

    def __repr__(self) -> str:
        return f"<UserEmail user_id={self.user_id} email={self.email_normalized!r}>"
