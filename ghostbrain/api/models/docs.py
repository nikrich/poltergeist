"""Request models for the docs assistant + export routes."""
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

DocsAssistMode = Literal["draft", "polish", "expand", "summarize", "continue", "translate"]
DocsAssistPlacement = Literal["doc", "selection", "cursor"]

# Client-chosen stream id (inline AI): becomes the turn key "docs:<id>".
STREAM_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,79}$"
# A language *name* only: letters plus space ( ) ' - — never a sentence.
_LANGUAGE_RE = re.compile(r"[^\W\d_](?:[^\W\d_]|[ ()'-]){0,39}")


class DocsAssistRequest(BaseModel):
    """One streamed assist turn over a jot (docs panel) or any vault note
    (inline AI). Exactly one of ``jot_id`` / ``path``."""

    jot_id: str | None = Field(default=None, min_length=1, max_length=128)
    path: str | None = Field(default=None, min_length=1, max_length=1024)
    stream_id: str | None = Field(default=None, pattern=STREAM_ID_PATTERN)
    mode: DocsAssistMode = "polish"
    instruction: str | None = None
    selection: str | None = None
    target_language: str | None = None
    # Markdown before the cursor (continue / insert-at-cursor). The prompt
    # keeps only the last BEFORE_CAP characters.
    before: str | None = None
    placement: DocsAssistPlacement | None = None

    @field_validator("target_language")
    @classmethod
    def _language_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not _LANGUAGE_RE.fullmatch(v):
            raise ValueError("target_language must be a language name")
        return v

    @model_validator(mode="after")
    def _shape(self) -> "DocsAssistRequest":
        if (self.jot_id is None) == (self.path is None):
            raise ValueError("send exactly one of jot_id or path")
        if self.mode == "translate":
            if not self.target_language:
                raise ValueError("translate needs target_language")
            if not (self.selection or "").strip():
                raise ValueError("translate needs a selection")
        if self.mode == "continue" and self.placement not in (None, "cursor"):
            raise ValueError("continue inserts at the cursor")
        return self

    @property
    def stream_key(self) -> str:
        """Key of this stream in main and in the turn registry (docs:<key>)."""
        return self.stream_id or self.jot_id or f"path:{self.path}"


class DocsAssistStopRequest(BaseModel):
    jot_id: str | None = None
    stream_id: str | None = Field(default=None, min_length=1, max_length=1100)

    @model_validator(mode="after")
    def _one(self) -> "DocsAssistStopRequest":
        if not (self.stream_id or self.jot_id):
            raise ValueError("send stream_id or jot_id")
        return self

    @property
    def key(self) -> str:
        return self.stream_id or self.jot_id or ""


class ConfluenceExportRequest(BaseModel):
    jot_id: str
    space_key: str
    parent_id: str | None = None
    title: str | None = None
    force_new: bool = False


class WriteDocRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    html: str = Field(..., min_length=1)


class WriteDocResponse(BaseModel):
    path: str
    title: str
    status: str = "applied"  # "pending": held for approval (spec B3), nothing written
    changeId: str | None = None
