"""Ontology API schemas."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OntologyStatus(BaseModel):
    available: bool
    reason: str | None = None


class OntologyProject(BaseModel):
    uuid: str
    id: str
    name: str
    context: str
    seeds: list[str]
    bound: int
    pending_items: int


class EnableRequest(BaseModel):
    project_id: str
    seeds: list[str] = Field(..., min_length=1)


class OnboardResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    binding_item: int | None
    in_: int = Field(alias="in")
    unsure: int
    auto_in: int
    auto_out: int
    scope_items: list[int]
    classified: int


class OntologyTopic(BaseModel):
    uid: str
    name: str
    status: str
    notes: int


class ExtractRequest(BaseModel):
    limit: int = Field(25, ge=1, le=200)


class ExtractStatus(BaseModel):
    running: bool
    project: str | None = None
    summary: dict | None = None
    last_error: str | None = None


class Evidence(BaseModel):
    aid: str
    path: str
    title: str
    quote: str
    locator: str


class Candidate(BaseModel):
    id: int
    kind: str
    name: str
    statement: str
    value: str | None
    confidence: float
    evidence: list[Evidence]


class BindingArtefact(BaseModel):
    aid: str
    path: str
    title: str


class ScopeNote(BaseModel):
    aid: str
    path: str
    title: str
    reason: str


class ScopeQuestion(BaseModel):
    topic_uid: str
    name: str
    lean: str
    notes: list[ScopeNote]


class OntologyItem(BaseModel):
    id: int
    type: Literal["binding", "candidate", "scope"]
    created: str
    candidate: Candidate | None
    artefacts: list[BindingArtefact]
    scope: ScopeQuestion | None = None


class OntologyActionRequest(BaseModel):
    action: Literal["ratify", "reject", "investigate", "yes", "no"]
    name: str | None = None
    statement: str | None = None
    value: str | None = None
    exclude: list[str] | None = None
    note: str | None = None


class ActionResult(BaseModel):
    ok: bool
    seq: int | None


class GraphNode(BaseModel):
    path: str
    title: str
    context: str
    kind: str
    degree: int
    ghost: bool
    hop: int
    note_path: str | None


class GraphEdge(BaseModel):
    source: str
    target: str
    weight: float
    kind: str


class OntologyGraph(BaseModel):
    focus: str
    depth: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool


class RevertRequest(BaseModel):
    project: str


class RebuildResult(BaseModel):
    applied: int


class OntologyNodeEvidence(BaseModel):
    aid: str
    note_path: str | None
    title: str
    quote: str | None
    locator: str | None


class OntologyNodeRelation(BaseModel):
    direction: Literal["out", "in"]
    type: str
    uid: str
    name: str
    kind: str


class OntologyNodeDetail(BaseModel):
    uid: str
    kind: str
    name: str
    statement: str | None
    value: str | None
    provenance: str | None
    ratified_at: str | None
    note_path: str | None
    generated_note_path: str | None
    evidence: list[OntologyNodeEvidence]
    relations: list[OntologyNodeRelation]
