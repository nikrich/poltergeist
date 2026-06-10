"""GET /v1/activity + GET /v1/activity/heatmap."""
import datetime as dt

from fastapi import APIRouter, Query

from ghostbrain.api.models.activity import ActivityRow, HeatmapResponse
from ghostbrain.api.repo.activity import (
    build_heatmap,
    list_activity,
    list_activity_for_date,
)

router = APIRouter(prefix="/v1/activity", tags=["activity"])


@router.get("/heatmap", response_model=HeatmapResponse)
def activity_heatmap(days: int = Query(365, ge=1, le=730)) -> dict:
    return build_heatmap(days=days)


@router.get("", response_model=list[ActivityRow])
def activity(
    windowMinutes: int = Query(240, ge=1, le=10_080),
    date: dt.date | None = Query(None),
) -> list[dict]:
    # `date` wins over windowMinutes when both are supplied (spec §2).
    # FastAPI's dt.date coercion gives the 422 for malformed dates for free.
    if date is not None:
        return list_activity_for_date(date)
    return list_activity(window_minutes=windowMinutes)
