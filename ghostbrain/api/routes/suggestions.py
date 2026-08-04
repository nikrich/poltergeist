"""GET /v1/suggestions."""
from fastapi import APIRouter

from ghostbrain.api.models.suggestion import Suggestion
from ghostbrain.api.repo.suggestions import list_suggestions

router = APIRouter(prefix="/v1/suggestions", tags=["suggestions"])


@router.get("", response_model=list[Suggestion])
def suggestions() -> list[dict]:
    return list_suggestions()
