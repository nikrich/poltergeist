"""Suggestion schema."""
from pydantic import BaseModel, ConfigDict


class Suggestion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    icon: str
    title: str
    body: str
    accent: bool = False
