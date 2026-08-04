"""Project registry schemas."""
from pydantic import BaseModel, Field


class Project(BaseModel):
    id: str
    context: str
    slug: str
    name: str
    description: str = ""
    archived: bool = False
    created_at: float


class CreateProjectRequest(BaseModel):
    context: str
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field("", max_length=400)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    description: str | None = Field(None, max_length=400)
    archived: bool | None = None
