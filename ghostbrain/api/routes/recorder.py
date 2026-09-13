"""Recorder control endpoints — POST /v1/recorder/{start,stop,clear},
GET /v1/recorder/status, plus the native-capture helpers under
/v1/recorder/capture/*."""
from fastapi import APIRouter, HTTPException

from ghostbrain.api.models.recorder import (
    CaptureHelperProbe,
    CaptureTargetRequest,
    RecorderStatus,
    StartRequest,
)
from ghostbrain.api.repo.recorder import (
    RecorderBusy,
    RecorderNotActive,
    RecorderUnsupportedError,
    clear,
    request_capture_permissions,
    set_capture_target,
    start,
    status,
    stop,
)
from ghostbrain.recorder.audio.base import CaptureUnavailableError
from ghostbrain.recorder.audio_capture import AudioRoutingError

router = APIRouter(prefix="/v1/recorder", tags=["recorder"])


@router.get("/status", response_model=RecorderStatus)
def get_status() -> dict:
    try:
        return status()
    except RecorderUnsupportedError as e:
        raise HTTPException(status_code=501, detail=str(e))


@router.post("/start", response_model=RecorderStatus)
def post_start(payload: StartRequest) -> dict:
    try:
        return start(title=payload.title, context=payload.context)
    except RecorderUnsupportedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except RecorderBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (AudioRoutingError, CaptureUnavailableError) as e:
        # 412 Precondition Failed — request is well-formed, but the system
        # isn't ready: output isn't routed to BlackHole (legacy path), or the
        # native helper lacks Screen Recording / Microphone permission.
        # Distinct from 500 so the renderer can show a fixable hint instead
        # of a generic error toast.
        raise HTTPException(status_code=412, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop", response_model=RecorderStatus)
def post_stop() -> dict:
    try:
        return stop()
    except RecorderUnsupportedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except RecorderNotActive as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/clear", response_model=RecorderStatus)
def post_clear() -> dict:
    try:
        return clear()
    except RecorderUnsupportedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except RecorderBusy as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/capture/request-permissions", response_model=CaptureHelperProbe)
def post_request_permissions() -> dict:
    """Trigger the macOS Screen Recording + Microphone prompts for the native
    helper and return the refreshed probe. Blocks until the user answers
    (bounded by the helper timeout)."""
    try:
        return request_capture_permissions()
    except RecorderUnsupportedError as e:
        raise HTTPException(status_code=501, detail=str(e))


@router.post("/capture/target", response_model=RecorderStatus)
def post_capture_target(payload: CaptureTargetRequest) -> dict:
    """Answer the native helper's "no meeting window found" prompt."""
    try:
        return set_capture_target(payload.choice, payload.window_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RecorderUnsupportedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except RecorderNotActive as e:
        raise HTTPException(status_code=409, detail=str(e))
