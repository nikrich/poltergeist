"""Live design session schemas — mirror desktop/src/shared/design-types.ts."""
from typing import Literal

from pydantic import BaseModel, Field

DesignCanvas = Literal["ui", "board"]
CanvasState = Literal["off", "active", "paused", "ended", "unavailable"]
UiKind = Literal["scratch", "worktree"]
InstallState = Literal["idle", "running", "failed", "done"]
BoardItemKind = Literal["event", "command", "aggregate", "policy", "read_model", "external", "actor", "hotspot"]


class RevInfo(BaseModel):
    rev: int
    at: str
    summary: str


class CanvasSnapshot(BaseModel):
    state: CanvasState
    rev: int
    running: bool
    buffered_s: float
    reason: str | None
    last_error: str | None
    revs: list[RevInfo]


class BoardContext(BaseModel):
    id: str
    name: str


class BoardItem(BaseModel):
    id: str
    kind: BoardItemKind
    label: str
    context: str | None
    order: float


class BoardLink(BaseModel):
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class BoardModel(BaseModel):
    contexts: list[BoardContext]
    items: list[BoardItem]
    links: list[BoardLink]


class CodebaseInfo(BaseModel):
    repo: str
    name: str
    app_dir: str
    worktree: str
    branch: str
    base: str


class CodebaseCandidate(BaseModel):
    path: str
    rel: str
    name: str
    frontend: bool


class CodebaseRequest(BaseModel):
    path: str | None = None


class DesignSessionSnapshot(BaseModel):
    id: str
    recording_title: str | None
    context: str
    project_id: str | None
    pack_id: str
    prototype_dir: str
    prototype_rel: str
    focus: DesignCanvas | None
    listening: bool
    canvases: dict[DesignCanvas, CanvasSnapshot]
    board: BoardModel | None
    ui_kind: UiKind
    codebase: CodebaseInfo | None
    install: InstallState
    codebase_confirmed: bool
    artefact_rel: str


class CanvasRequest(BaseModel):
    canvas: DesignCanvas


class PauseRequest(BaseModel):
    canvas: Literal["ui", "board", "both"] = "both"


class ResumeRequest(BaseModel):
    canvas: DesignCanvas | None = None


class NudgeRequest(BaseModel):
    canvas: DesignCanvas | None = None
    text: str = Field(..., min_length=1, max_length=2000)


class UpdateRequest(BaseModel):
    canvas: DesignCanvas | None = None


class UndoRequest(BaseModel):
    token: str = Field(..., min_length=1)


class ConfigRequest(BaseModel):
    project_id: str | None = None
    pack_id: str | None = None


class BuildErrorRequest(BaseModel):
    rev: int
    message: str = Field(..., max_length=20_000)


class RevertRequest(BaseModel):
    canvas: DesignCanvas
    rev: int = Field(..., ge=0)


class EjectResponse(BaseModel):
    path: str
