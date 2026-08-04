"""Models for POST /v1/llm/run."""
from typing import Any

from pydantic import BaseModel


class LlmRunRequest(BaseModel):
    prompt: str
    system: str | None = None
    model: str = "sonnet"
    jsonSchema: dict | None = None
    timeoutSeconds: int = 600
    budgetUsd: float | None = None


class LlmRunResponse(BaseModel):
    text: str
    structured: Any | None = None
    error: str | None = None
    costUsd: float | None = None
    durationMs: int | None = None
