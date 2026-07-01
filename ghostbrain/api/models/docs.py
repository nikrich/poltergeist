"""Request models for the docs assistant + export routes."""
from typing import Literal

from pydantic import BaseModel, Field


class DocsAssistRequest(BaseModel):
    jot_id: str
    mode: Literal["draft", "polish", "expand", "summarize"] = "polish"
    instruction: str | None = None
    selection: str | None = None


class DocsAssistStopRequest(BaseModel):
    jot_id: str


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
