"""Note-viewer schemas + jot list/detail schemas."""
from typing import Any, Literal

from pydantic import BaseModel, Field


class Note(BaseModel):
    path: str  # vault-relative
    title: str
    body: str
    frontmatter: dict[str, Any]


RoutingStatus = Literal["pending", "routed", "manual_review"]
# "path"/"llm"/"fallback" come from the worker router; "user" from manual re-routes.
RoutingMethod = Literal["path", "llm", "user", "fallback"]


class NoteListItem(BaseModel):
    """One row in the Jot screen tree/list."""

    id: str
    path: str  # vault-relative
    title: str
    excerpt: str  # first ~120 chars of body
    context: str | None  # None while pending
    routingStatus: RoutingStatus
    tags: list[str]
    created: str  # ISO8601
    updated: str  # ISO8601


class NotesPage(BaseModel):
    total: int
    items: list[NoteListItem]


class CreateNoteRequest(BaseModel):
    body: str
    capturedAt: str | None = None  # ISO8601; omit to let the server timestamp the jot
    route: bool = True  # set False to skip routing (stays pending in inbox)


class UpdateNoteRequest(BaseModel):
    body: str


class UpdateNoteBodyRequest(BaseModel):
    """PATCH /v1/notes/body — rich-editor save for any vault note by path."""

    path: str  # vault-relative
    body: str


class RouteNoteRequest(BaseModel):
    context: str
    project: str | None = None


class ExtractPhotoRequest(BaseModel):
    assetPath: str = Field(min_length=1, max_length=500)


class UpsertNoteRequest(BaseModel):
    path: str
    content: str
