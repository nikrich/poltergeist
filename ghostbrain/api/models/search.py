"""Semantic-search schemas."""
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(10, ge=1, le=50)
    # Only notes indexed within the last N days ("today" → 1, "this week" → 7).
    days: int | None = Field(None, ge=1, le=3650)


class SearchHit(BaseModel):
    path: str  # vault-relative, e.g. "20-contexts/acme/jira/tickets/ABC-1.md"
    title: str
    snippet: str
    score: float  # cosine similarity, [-1, 1]


class SearchResponse(BaseModel):
    query: str
    total: int
    items: list[SearchHit]
