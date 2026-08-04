"""GET /v1/agenda?date=YYYY-MM-DD."""
from datetime import date as dt_date

from fastapi import APIRouter, Query

from ghostbrain.api.models.agenda import AgendaItem
from ghostbrain.api.repo.agenda import list_agenda

router = APIRouter(prefix="/v1/agenda", tags=["agenda"])


@router.get("", response_model=list[AgendaItem])
def agenda(
    date: str = Query(default_factory=lambda: dt_date.today().isoformat()),
) -> list[dict]:
    return list_agenda(date=date)
