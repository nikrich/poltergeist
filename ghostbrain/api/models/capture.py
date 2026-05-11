"""Capture schemas."""
from pydantic import BaseModel, ConfigDict, Field


class CaptureSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    title: str
    snippet: str
    from_: str = Field(alias="from")
    tags: list[str]
    unread: bool
    capturedAt: str


class Capture(CaptureSummary):
    body: str
    extracted: dict | None


class CapturesPage(BaseModel):
    total: int
    items: list[CaptureSummary]
