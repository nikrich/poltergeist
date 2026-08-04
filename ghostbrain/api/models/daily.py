"""Daily-digest schemas."""
from pydantic import BaseModel


class DailyDigest(BaseModel):
    id: str
    date: str
    title: str
    snippet: str
    noteCount: int


class DailyPage(BaseModel):
    total: int
    items: list[DailyDigest]
