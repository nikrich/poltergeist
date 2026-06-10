"""Chat conversation schemas."""
from typing import Literal

from pydantic import BaseModel, Field


class ChatToolUse(BaseModel):
    name: str
    summary: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    tools: list[ChatToolUse] = []
    interrupted: bool = False


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    message_count: int


class Conversation(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    claude_session_id: str | None = None
    messages: list[ChatMessage] = []


class ChatMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class RenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
