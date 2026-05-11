"""GET /v1/daily."""
from fastapi import APIRouter, Query

from ghostbrain.api.models.daily import DailyPage
from ghostbrain.api.repo.daily import list_daily

router = APIRouter(prefix="/v1/daily", tags=["daily"])


@router.get("", response_model=DailyPage)
def daily(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    return list_daily(limit=limit, offset=offset)
