"""Recorder control endpoints — POST /v1/recorder/{start,stop,clear},
GET /v1/recorder/status, GET /v1/recorder/live (SSE live transcript), plus
the native-capture helpers under /v1/recorder/capture/*."""
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ghostbrain.api.models.recorder import (
    CaptureHelperProbe,
    CaptureTargetRequest,
    RecorderStatus,
    StartRequest,
)
from ghostbrain.api.repo.recorder import (
    RecorderBusy,
    RecorderNotActive,
    RecorderPrereqsMissing,
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

log = logging.getLogger("ghostbrain.api.recorder_routes")

router = APIRouter(prefix="/v1/recorder", tags=["recorder"])


@router.get("/status", response_model=RecorderStatus)
def get_status() -> dict:
    try:
        return status()
    except RecorderUnsupportedError as e:
        raise HTTPException(status_code=501, detail=str(e))


@router.get("/live")
def get_live() -> StreamingResponse:
    """The current recording's live transcript: already-transcribed segments
    first, then new ones as they land, until an ``end`` event."""
    from ghostbrain.recorder import live

    def gen():
        # Sync generator: starlette threadpools it and closes it on client
        # disconnect, which unsubscribes from the session.
        for event in live.follow():
            if event is None:
                yield ": keepalive\n\n"
            else:
                yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/levels")
def get_levels() -> StreamingResponse:
    """Audio levels (0..1 per 100 ms) of the recording in progress, for the
    waveform; ends when the recording does."""
    from pathlib import Path

    from ghostbrain.recorder import levels

    try:
        st = status()
    except RecorderUnsupportedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    wav = st.get("wavPath") if st.get("phase") == "recording" else None

    def gen():
        if wav:
            for chunk in levels.follow_levels(Path(wav)):
                if chunk is None:
                    yield ": keepalive\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'levels', 'levels': chunk})}\n\n"
        yield f"data: {json.dumps({'type': 'end'})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/start", response_model=RecorderStatus)
def post_start(payload: StartRequest) -> dict:
    try:
        return start(title=payload.title, context=payload.context)
    except RecorderUnsupportedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except RecorderBusy as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (AudioRoutingError, CaptureUnavailableError, RecorderPrereqsMissing) as e:
        # 412 Precondition Failed — request is well-formed, but the system
        # isn't ready: output isn't routed to BlackHole (legacy path), the
        # native helper lacks Screen Recording / Microphone permission, or a
        # prerequisite binary/model is missing. The detail names the exact fix,
        # distinct from 500 so the renderer can show a fixable hint.
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
