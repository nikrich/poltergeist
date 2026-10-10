"""Live design session — GET /v1/design/live (SSE), GET /v1/design/session,
the session actions under POST /v1/design/session/* and GET
/v1/design/codebases (repos for the codebase picker).

Importing this module registers the design listener with live
transcription, so the API process starts a session for every recording.
"""
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ghostbrain.api.models.design import (
    BuildErrorRequest,
    CanvasRequest,
    CodebaseCandidate,
    CodebaseRequest,
    ConfigRequest,
    DesignSessionSnapshot,
    EjectResponse,
    NudgeRequest,
    PauseRequest,
    ResumeRequest,
    RevertRequest,
    UndoRequest,
    UpdateRequest,
)
from ghostbrain.api.repo.recorder import RecorderUnsupportedError, status
from ghostbrain.design import codebases, listener
from ghostbrain.design import session as design_session

log = logging.getLogger("ghostbrain.api.design_routes")

router = APIRouter(prefix="/v1/design", tags=["design"])


def _recording_wav() -> Path | None:
    try:
        st = status()
    except RecorderUnsupportedError:
        return None
    if st.get("phase") == "recording" and st.get("wavPath"):
        return Path(st["wavPath"])
    return None


def _ensure_for_recording() -> design_session.DesignSession | None:
    """The session of the recording in progress, created on demand (live
    transcription off, or the app restarted before /live connected)."""
    wav = _recording_wav()
    if wav is None:
        return None
    if design_session.get(wav) is None:
        try:
            listener.start_for_recording(wav)
        except Exception:
            log.exception("could not start the design session for %s", wav.name)
    return design_session.get(wav)


def _session() -> design_session.DesignSession:
    s = _ensure_for_recording() or design_session.current()
    if s is None:
        raise HTTPException(status_code=409, detail="No design session: start a recording first")
    return s


def _act(fn: Callable[[design_session.DesignSession], Any]) -> dict:
    s = _session()
    try:
        event = fn(s)
    except design_session.SessionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"event": event, "session": s.snapshot()}


@router.get("/live")
def get_live() -> StreamingResponse:
    """The design session of the recording in progress (or the one that just
    ended): a snapshot first, then events until ``end``. ``idle`` + ``end``
    when there is neither."""
    wav = _recording_wav()
    # The app restarted mid-meeting: this sidecar has no session for the
    # recording yet. Start one; it restores from session.jsonl if it can.
    if wav is not None and design_session.get(wav) is None:
        try:
            listener.start_for_recording(wav)
        except Exception:
            log.exception("could not start the design session for %s", wav.name)
    session = design_session.get(wav) if wav is not None else design_session.current()

    def gen():
        if session is None:
            yield f"data: {json.dumps({'type': 'idle'})}\n\n"
            yield f"data: {json.dumps({'type': 'end'})}\n\n"
            return
        for event in design_session.follow(session):
            if event is None:
                yield ": keepalive\n\n"
            else:
                yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/session", response_model=DesignSessionSnapshot)
def get_session() -> dict:
    s = design_session.current()
    if s is None:
        raise HTTPException(status_code=404, detail="No design session")
    return s.snapshot()


@router.post("/session/start")
def post_start(payload: CanvasRequest) -> dict:
    return _act(lambda s: s.start(payload.canvas))


@router.post("/session/pause")
def post_pause(payload: PauseRequest) -> dict:
    return _act(lambda s: s.pause(payload.canvas))


@router.post("/session/resume")
def post_resume(payload: ResumeRequest) -> dict:
    return _act(lambda s: s.resume(payload.canvas))


@router.post("/session/nudge")
def post_nudge(payload: NudgeRequest) -> dict:
    return _act(lambda s: s.nudge(payload.canvas, payload.text))


@router.post("/session/update")
def post_update(payload: UpdateRequest) -> dict:
    return _act(lambda s: s.force_update(payload.canvas))


@router.post("/session/undo")
def post_undo(payload: UndoRequest) -> dict:
    return _act(lambda s: s.undo(payload.token))


@router.post("/session/config")
def post_config(payload: ConfigRequest) -> dict:
    fields: dict[str, Any] = {}
    if "project_id" in payload.model_fields_set:
        fields["project_id"] = payload.project_id
    if payload.pack_id:
        fields["pack_id"] = payload.pack_id
    return _act(lambda s: s.set_config(**fields))


@router.post("/session/codebase")
def post_codebase(payload: CodebaseRequest) -> dict:
    return _act(lambda s: s.set_codebase(payload.path))


@router.get("/codebases", response_model=list[CodebaseCandidate])
def get_codebases(q: str = Query("", max_length=200), refresh: bool = False) -> list[dict]:
    """Repos under the configured code roots matching ``q``, frontends first."""
    if refresh:
        codebases.scan(refresh=True)
    if q.strip():
        found = codebases.search(q)
    else:
        found = sorted(codebases.scan(), key=lambda c: (not c.frontend, c.rel))[:50]
    return [c.to_dict() for c in found]


@router.post("/session/build-error")
def post_build_error(payload: BuildErrorRequest) -> dict:
    return _act(lambda s: s.report_build_error(payload.rev, payload.message))


@router.post("/session/revert")
def post_revert(payload: RevertRequest) -> dict:
    return _act(lambda s: s.revert(payload.canvas, payload.rev))


@router.post("/session/eject", response_model=EjectResponse)
def post_eject() -> dict:
    s = _session()
    try:
        path = s.eject()
    except design_session.SessionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write the project files: {e}")
    return {"path": str(path)}
