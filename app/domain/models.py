from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import EventStatus, EventType, Platform


def _attach_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class EventCreate(BaseModel):
    type: EventType
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: datetime | None = None
    remind_at: datetime | None = None
    rrule: str | None = Field(default=None, max_length=255)
    status: EventStatus = EventStatus.PENDING
    source: Platform | None = None

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        stripped = " ".join(value.split())
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped


class EventUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    starts_at: datetime | None = None
    remind_at: datetime | None = None
    rrule: str | None = Field(default=None, max_length=255)
    status: EventStatus | None = None


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    type: EventType
    title: str
    description: str | None = None
    starts_at: datetime | None = None
    remind_at: datetime | None = None
    rrule: str | None = None
    status: EventStatus
    source: Platform | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _normalise_datetimes(self) -> "EventRead":
        for field in ("starts_at", "remind_at", "created_at", "updated_at"):
            value = getattr(self, field)
            if value is not None and value.tzinfo is None:
                setattr(self, field, _attach_utc(value))
        return self


class AssistantResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    text: str
    audio: bytes | None = None
    audio_format: str | None = None
    events: list[EventRead] = Field(default_factory=list)
    needs_clarification: bool = False
    intent: str | None = None

    @property
    def audio_mime_type(self) -> str | None:
        if not self.audio:
            return None
        return {
            "opus": "audio/ogg",
            "ogg": "audio/ogg",
            "wav": "audio/wav",
            "wav16": "audio/wav",
            "mp3": "audio/mpeg",
        }.get((self.audio_format or "").lower(), "application/octet-stream")
