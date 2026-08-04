"""Chat conversation schemas."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    project: str | None = None


class Conversation(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    claude_session_id: str | None = None
    project: str | None = None
    messages: list[ChatMessage] = []


class ChatMessageRequest(BaseModel):
    text: str = Field("", max_length=4000)
    attachment_paths: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _require_text_or_attachments(self) -> "ChatMessageRequest":
        if not self.text.strip() and not self.attachment_paths:
            raise ValueError("message must have text or attachments")
        return self


class UpdateConversationRequest(BaseModel):
    """Partial update: fields absent from the payload stay untouched.

    ``project`` is a ``context/slug`` registry key; explicit null unfiles.
    ``model_fields_set`` distinguishes omitted from null at the route.
    """

    title: str | None = Field(None, min_length=1, max_length=200)
    project: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def _something_to_update(self) -> "UpdateConversationRequest":
        if not self.model_fields_set:
            raise ValueError("nothing to update — pass title and/or project")
        return self


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
