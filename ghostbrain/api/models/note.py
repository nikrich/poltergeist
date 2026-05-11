"""Note-viewer schemas."""
from typing import Any

from pydantic import BaseModel


class Note(BaseModel):
    path: str  # vault-relative
    title: str
    body: str
    frontmatter: dict[str, Any]
