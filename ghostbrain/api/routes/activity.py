"""GET /v1/activity."""
from fastapi import APIRouter, Query

from ghostbrain.api.models.activity import ActivityRow
from ghostbrain.api.repo.activity import list_activity

router = APIRouter(prefix="/v1/activity", tags=["activity"])


@router.get("", response_model=list[ActivityRow])
def activity(windowMinutes: int = Query(240, ge=1, le=10_080)) -> list[dict]:
    return list_activity(window_minutes=windowMinutes)
