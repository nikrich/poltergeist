"""GET + POST /v1/settings/recorder — vault-level recorder settings."""
from fastapi import APIRouter

from ghostbrain.api.models.settings import RecorderSettings, UpdateRecorderSettings
from ghostbrain.api.repo.settings import get_recorder_settings, update_recorder_settings

router = APIRouter(prefix="/v1/settings", tags=["settings"])


@router.get("/recorder", response_model=RecorderSettings)
def read_recorder() -> dict:
    return get_recorder_settings()


@router.post("/recorder", response_model=RecorderSettings)
def write_recorder(payload: UpdateRecorderSettings) -> dict:
    return update_recorder_settings(
        enabled=payload.enabled,
        excluded_titles=payload.excluded_titles,
        manual_context=payload.manual_context,
    )
