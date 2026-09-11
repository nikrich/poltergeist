"""Recorder control endpoints — POST /v1/recorder/{start,stop,clear}, GET /v1/recorder/status."""
import logging

from fastapi import APIRouter, HTTPException

from ghostbrain.api.models.recorder import RecorderStatus, StartRequest
from ghostbrain.api.repo.recorder import (
    RecorderBusy,
    RecorderNotActive,
    RecorderPrereqsMissing,
    RecorderUnsupportedError,
    clear,
    start,
    status,
    stop,
)
from ghostbrain.recorder.audio_capture import AudioRoutingError

log = logging.getLogger("ghostbrain.api.recorder_routes")

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
    except (AudioRoutingError, RecorderPrereqsMissing) as e:
        # 412 Precondition Failed — well-formed request, system not ready; the
        # detail names the exact fix (device to select, brew formula to install).
        raise HTTPException(status_code=412, detail=str(e))
    except (RuntimeError, OSError) as e:
        log.exception("recorder start failed")
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
