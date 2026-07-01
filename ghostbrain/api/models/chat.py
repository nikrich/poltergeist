"""Chat conversation schemas."""
from typing import Literal

from pydantic import BaseModel, Field


class ChatToolUse(BaseModel):
    name: str
    summary: str


class Attachment(BaseModel):
    path: str
    title: str
    kind: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    tools: list[ChatToolUse] = []
    interrupted: bool = False
    attachments: list[Attachment] = []


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
    attachment_paths: list[str] = Field(default_factory=list, max_length=10)


class RenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class AttachmentFile(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    mime: str = Field("", max_length=255)
    content_b64: str = Field(..., min_length=1)


class AttachmentUploadRequest(BaseModel):
    files: list[AttachmentFile] = Field(..., min_length=1)


class AttachmentUploadResponse(BaseModel):
    attachments: list[Attachment]


class ChatExportResponse(BaseModel):
    jot_id: str
    path: str
    routingStatus: str
    context: str | None = None
    project: str | None = None
    title: str
