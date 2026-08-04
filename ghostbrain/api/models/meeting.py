"""Meeting schemas."""
from pydantic import BaseModel, ConfigDict, Field


class PastMeeting(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    date: str
    dur: str
    speakers: int
    tags: list[str]
    path: str | None = None


class MeetingsPage(BaseModel):
    total: int
    items: list[PastMeeting]


class EventSnapshot(BaseModel):
    """Frozen view of a calendar event used for cache invalidation."""
    model_config = ConfigDict(populate_by_name=True)

    title: str
    start: str
    end: str
    with_: list[str] = Field(default_factory=list, alias="with")
    location: str = ""
    description: str = ""
    hash: str


class RelatedItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    path: str
    title: str
    source: str
    snippet: str
    score: float


class Prep(BaseModel):
    """Prep notes for an upcoming meeting."""
    model_config = ConfigDict(populate_by_name=True)

    event_id: str = Field(alias="eventId")
    brief: str | None = None
    related: list[RelatedItem] = Field(default_factory=list)
    event_snapshot: EventSnapshot = Field(alias="eventSnapshot")
    generated_at: str = Field(alias="generatedAt")
    error: str | None = None
