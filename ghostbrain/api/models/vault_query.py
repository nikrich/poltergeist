"""Payloads for POST /v1/vault/query and PATCH /v1/vault/status (C2)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ghostbrain.templates.query import MAX_QUERY_CHARS

# Transport cap. The parser reports anything over MAX_QUERY_CHARS as an
# inline diagnostic; only absurd bodies are refused outright.
MAX_QUERY_BODY_CHARS = MAX_QUERY_CHARS * 4


class VaultQueryRequest(BaseModel):
    query: str = Field(..., max_length=MAX_QUERY_BODY_CHARS)


class VaultQueryRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    path: str
    title: str
    context: str
    status: str | None
    created: str | None
    snippet: str
    etag: str | None


class VaultQueryDiagnostic(BaseModel):
    line: int
    col: int
    severity: Literal["error", "warning", "info"]
    message: str
    code: str


class VaultQueryResponse(BaseModel):
    results: list[VaultQueryRow]
    diagnostics: list[VaultQueryDiagnostic]
    indexing: bool
    partial: bool


class NoteStatusRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    status: Literal["done", "open"]


class NoteStatusResponse(BaseModel):
    path: str
    status: Literal["done", "open"]
    etag: str | None
