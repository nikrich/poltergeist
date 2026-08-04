"""Schemas for the /v1/import route family."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ImportSpace(BaseModel):
    site: str
    siteSlug: str
    key: str
    name: str
    context: str


class ImportPage(BaseModel):
    site: str
    id: str
    title: str
    # "page" = importable + selectable; "folder" = navigation node only.
    type: Literal["page", "folder"] = "page"
    parentId: str | None = None
    hasChildren: bool
    updatedAt: str | None = None
    version: int | None = None
    space: str | None = None


class ConfluencePagesResponse(BaseModel):
    items: list[ImportPage]
    # Confluence v1 paging is start/limit; the cursor is the stringified
    # next start offset. None when the last page was not full.
    nextCursor: str | None = None


class ImportJiraIssue(BaseModel):
    site: str
    key: str
    summary: str
    status: str | None = None
    project: str | None = None
    updatedAt: str | None = None


class ImportItemRequest(BaseModel):
    kind: Literal["confluence_page", "jira_issue"]
    site: str
    id: str | None = None
    key: str | None = None

    @model_validator(mode="after")
    def _check_identifier(self) -> "ImportItemRequest":
        if self.kind == "confluence_page" and not self.id:
            raise ValueError("confluence_page items require `id`")
        if self.kind == "jira_issue" and not self.key:
            raise ValueError("jira_issue items require `key`")
        return self


class ImportRequest(BaseModel):
    # Spec: max 50 items per request; pydantic turns violations into 422.
    items: list[ImportItemRequest] = Field(..., min_length=1, max_length=50)


class ImportItemResult(BaseModel):
    kind: str
    id: str | None = None
    key: str | None = None
    ok: bool
    path: str | None = None
    context: str | None = None
    updated: bool | None = None
    error: str | None = None


class ImportResponse(BaseModel):
    results: list[ImportItemResult]
