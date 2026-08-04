"""Ask-the-archive RAG schemas."""
from pydantic import BaseModel, Field

from ghostbrain.api.models.search import SearchHit


class AnswerRequest(BaseModel):
    q: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(8, ge=1, le=20)


class AnswerResponse(BaseModel):
    query: str
    answer: str          # markdown with [N] citations referencing sources
    sources: list[SearchHit]
    error: str | None = None
