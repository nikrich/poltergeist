"""Recorder control endpoints — POST /v1/recorder/{start,stop,clear}, GET /v1/recorder/status."""
from fastapi import APIRouter, HTTPException

from ghostbrain.api.models.recorder import RecorderStatus, StartRequest
from ghostbrain.api.repo.recorder import (
    RecorderBusy,
    RecorderNotActive,
    clear,
    start,
    status,
    stop,
)

router = APIRouter(prefix="/v1/recorder", tags=["recorder"])


@router.get("/status", response_model=RecorderStatus)
def get_status() -> dict:
    return status()


@router.post("/start", response_model=RecorderStatus)
def post_start(payload: StartRequest) -> dict:
    try:
        return start(title=payload.title, context=payload.context)
    except RecorderBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop", response_model=RecorderStatus)
def post_stop() -> dict:
    try:
        return stop()
    except RecorderNotActive as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/clear", response_model=RecorderStatus)
def post_clear() -> dict:
    try:
        return clear()
    except RecorderBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
