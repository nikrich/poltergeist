"""Docs library schemas (spec §3)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocSummary(BaseModel):
    doc_id: str
    title: str
    kind: str
    mime: str
    size: int
    created: str
    context: str
    project: str | None = None
    folder: str
    original: str
    original_path: str
    note_path: str
    index_status: str
    pages: int | None = None
    excerpt: str = ""


class UploadDocResponse(DocSummary):
    duplicate: bool


class DocDetail(DocSummary):
    body: str


class FolderNode(BaseModel):
    name: str
    path: str
    folders: list["FolderNode"]
    docs: list[DocSummary]


class DocScope(BaseModel):
    context: str
    project: str | None = None
    name: str
    archived: bool
    folders: list[FolderNode]
    docs: list[DocSummary]


class AttentionItem(BaseModel):
    kind: Literal["orphan_note", "unclaimed_original", "index_failed"]
    context: str
    project: str | None = None
    folder: str
    name: str
    doc_id: str | None = None


class LibraryTree(BaseModel):
    scopes: list[DocScope]
    attention: list[AttentionItem]


class UploadDocRequest(BaseModel):
    context: str
    project: str | None = None
    folder: str = ""
    name: str = Field(..., min_length=1, max_length=255)
    mime: str = Field("", max_length=255)
    content_b64: str


class PatchDocRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    context: str | None = None
    project: str | None = None
    folder: str = ""


class FolderRef(BaseModel):
    context: str
    project: str | None = None
    path: str


class MoveFolderRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: FolderRef = Field(..., alias="from")
    to: FolderRef


class AdoptRequest(BaseModel):
    context: str
    project: str | None = None
    folder: str = ""
    name: str = Field(..., min_length=1, max_length=255)


class RemoveOrphanRequest(BaseModel):
    doc_id: str
