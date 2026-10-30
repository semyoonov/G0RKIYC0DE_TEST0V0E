from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.user import _enum_values
from app.domain.enums import EventStatus, EventType, Platform

if TYPE_CHECKING:
    from app.db.models.user import User


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_user_starts_at", "user_id", "starts_at"),
        Index("ix_events_remind_at", "remind_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[EventType] = mapped_column(
        Enum(EventType, native_enum=False, length=16, values_callable=_enum_values)
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    remind_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, native_enum=False, length=16, values_callable=_enum_values),
        default=EventStatus.PENDING,
        index=True,
    )
    source: Mapped[Platform | None] = mapped_column(
        Enum(Platform, native_enum=False, length=16, values_callable=_enum_values)
    )
    rrule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="events")

    def __repr__(self) -> str:
        return f"<Event id={self.id} type={self.type} title={self.title!r} starts_at={self.starts_at}>"
