"""Recorder control endpoints — POST /v1/recorder/{start,stop,clear}, GET /v1/recorder/status."""
from fastapi import APIRouter, HTTPException

from ghostbrain.api.models.recorder import RecorderStatus, StartRequest
from ghostbrain.api.repo.recorder import (
    RecorderBusy,
    RecorderNotActive,
    RecorderUnsupportedError,
    clear,
    start,
    status,
    stop,
)
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
    except AudioRoutingError as e:
        # 412 Precondition Failed — request is well-formed, but the
        # system isn't ready (audio output isn't routed to BlackHole).
        # Distinct from 500 so the renderer can show a fixable hint
        # ("switch macOS output to Ghost Brain") instead of a generic
        # error toast.
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
