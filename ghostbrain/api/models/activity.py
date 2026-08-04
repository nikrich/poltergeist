"""Activity row + heatmap schemas."""
from pydantic import BaseModel, ConfigDict


class ActivityRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    verb: str
    subject: str
    atRelative: str
    at: str
    path: str | None = None


class HeatmapDay(BaseModel):
    date: str  # YYYY-MM-DD
    count: int
    bySource: dict[str, int]


class HeatmapResponse(BaseModel):
    days: list[HeatmapDay]
    total: int
    maxCount: int
