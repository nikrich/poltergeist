"""Payloads for GET /v1/vault/suggest and GET /v1/vault/backlinks."""
from typing import Literal

from pydantic import BaseModel, ConfigDict


class SuggestItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    kind: Literal["page", "tag", "person"]
    label: str
    path: str | None
    context: str
    detail: str
    count: int | None


class SuggestResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    items: list[SuggestItem]
    indexing: bool


class Backlink(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    path: str
    title: str
    context: str
    snippet: str


class BacklinksResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    items: list[Backlink]
    indexing: bool


class ResolveResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    path: str
    exists: bool
    indexing: bool
