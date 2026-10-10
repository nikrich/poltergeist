"""Design artefacts — GET /v1/design/artefacts (list), GET /v1/design/artefact
(detail) and POST /v1/design/artefacts/{remove-worktree,eject}.

Importing this module registers ``artefacts.link_meeting`` with the
recorder's ``on_transcribed`` hook, so the API process links every design
session to its meeting note.
"""
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ghostbrain.api.models.design import EjectResponse
from ghostbrain.design import artefacts

router = APIRouter(prefix="/v1/design", tags=["design"])


class ArtefactCodebase(BaseModel):
    repo: str
    name: str
    app_dir: str
    worktree: str
    branch: str
    base: str
    missing: bool


class ArtefactSummary(BaseModel):
    id: str
    title: str
    kind: str  # prototype | worktree | board
    board: bool
    date: str
    context: str
    project: str | None = None
    meeting: str | None = None
    meeting_path: str | None = None
    ui_rev: int
    board_rev: int
    codebase: ArtefactCodebase | None = None


class ArtefactDetail(ArtefactSummary):
    folder: str
    revs: list[dict[str, Any]]
    board_model: dict[str, Any] | None = None
    design_system: str | None = None


class ArtefactRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=1000)


class RemoveWorktreeResponse(BaseModel):
    removed: bool
    branch_kept: bool
    reason: str | None = None


def _not_found(artefact_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"artefact not found: {artefact_id}")


@router.get("/artefacts", response_model=list[ArtefactSummary])
def list_artefacts() -> list[dict]:
    return artefacts.list_artefacts()


@router.get("/artefact", response_model=ArtefactDetail)
def get_artefact(id: str = Query(..., min_length=1, max_length=1000)) -> dict:
    detail = artefacts.detail(id)
    if detail is None:
        raise _not_found(id)
    return detail


@router.post("/artefacts/remove-worktree", response_model=RemoveWorktreeResponse)
def post_remove_worktree(payload: ArtefactRequest) -> dict:
    try:
        return artefacts.remove_worktree(payload.id)
    except ValueError:
        raise _not_found(payload.id)
    except artefacts.ArtefactError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/artefacts/eject", response_model=EjectResponse)
def post_eject(payload: ArtefactRequest) -> dict:
    try:
        path = artefacts.eject(payload.id)
    except ValueError:
        raise _not_found(payload.id)
    except artefacts.ArtefactError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Could not write the project files: {e}")
    return {"path": str(path)}
