"""GET + POST /v1/settings/recorder, GET + PUT /v1/settings/llm — vault-level settings."""
from fastapi import APIRouter, HTTPException

from ghostbrain.api.models.settings import (
    LlmSettings,
    RecorderSettings,
    UpdateLlmSettings,
    UpdateRecorderSettings,
)
from ghostbrain.api.repo.settings import (
    get_llm_settings,
    get_recorder_settings,
    update_llm_settings,
    update_recorder_settings,
)

router = APIRouter(prefix="/v1/settings", tags=["settings"])


@router.get("/recorder", response_model=RecorderSettings)
def read_recorder() -> dict:
    return get_recorder_settings()


@router.post("/recorder", response_model=RecorderSettings)
def write_recorder(payload: UpdateRecorderSettings) -> dict:
    try:
        return update_recorder_settings(
            enabled=payload.enabled,
            excluded_titles=payload.excluded_titles,
            manual_context=payload.manual_context,
            capture_backend=payload.capture_backend,
            capture_slides=payload.capture_slides,
            slide_fps=payload.slide_fps,
            slide_fallback=payload.slide_fallback,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/llm", response_model=LlmSettings)
def read_llm() -> dict:
    return get_llm_settings()


@router.put("/llm", response_model=LlmSettings)
def write_llm(payload: UpdateLlmSettings) -> dict:
    try:
        return update_llm_settings(**payload.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
