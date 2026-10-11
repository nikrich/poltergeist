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
    context: str | None = None
    project: str | None = None
    folder: str | None = None
    auto_filed: Literal["pending", "done", "skipped"] = "skipped"


class ChatTreeChat(ConversationSummary):
    unknown_location: bool = False


class ChatFolderNode(BaseModel):
    name: str
    path: str
    folders: list["ChatFolderNode"] = []
    chats: list[ChatTreeChat] = []


class ChatScope(BaseModel):
    context: str
    project: str | None = None
    name: str
    archived: bool = False
    folders: list[ChatFolderNode] = []
    chats: list[ChatTreeChat] = []


class ChatTree(BaseModel):
    unfiled: list[ChatTreeChat] = []
    scopes: list[ChatScope] = []


class Conversation(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    claude_session_id: str | None = None
    context: str | None = None
    project: str | None = None
    folder: str | None = None
    auto_filed: Literal["pending", "done", "skipped"] = "skipped"
    messages: list[ChatMessage] = []


class ChatMessageRequest(BaseModel):
    # No length cap: users paste whole documents into chat. The only hard
    # bound left is the OS argv limit (~1 MB on macOS) for the CLIs that take
    # the prompt as an argument, which is far beyond any model's context.
    text: str = ""
    attachment_paths: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _require_text_or_attachments(self) -> "ChatMessageRequest":
        if not self.text.strip() and not self.attachment_paths:
            raise ValueError("message must have text or attachments")
        return self


class UpdateConversationRequest(BaseModel):
    """Partial update; absent fields stay untouched (model_fields_set).

    Location: send ``context`` (null unfiles) with optional ``project`` slug
    and ``folder``. Legacy clients send only ``project`` as ``context/slug``
    (null unfiles) — still accepted.
    """

    title: str | None = Field(None, min_length=1, max_length=200)
    context: str | None = Field(None, max_length=200)
    project: str | None = Field(None, max_length=200)
    folder: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _something_to_update(self) -> "UpdateConversationRequest":
        if not self.model_fields_set:
            raise ValueError("nothing to update — pass title and/or a location")
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
