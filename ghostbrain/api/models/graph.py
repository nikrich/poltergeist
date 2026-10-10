"""Vault graph payload."""
from pydantic import BaseModel, ConfigDict


class GraphNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    path: str
    title: str
    context: str
    tags: list[str]
    x: float
    y: float
    degree: int
    updated: str | None
    kind: str = "note"  # person | meeting | decision | action | ticket | doc | jot | note


class GraphEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    source: str
    target: str
    weight: float
    kind: str  # "related" | "wikilink"


class GraphRegion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    label: str
    color: str
    count: int


class GraphResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    regions: list[GraphRegion]


class EgoNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    path: str  # vault path, or a ghost's link key ("someday idea.md")
    title: str
    context: str
    kind: str  # person | meeting | decision | action | ticket | doc | jot | note
    degree: int  # vault-wide link count
    ghost: bool  # linked but not written yet
    hop: int  # BFS distance from the focus


class EgoEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    source: str
    target: str
    weight: float
    kind: str  # "related" | "wikilink"


class EgoGraphResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    focus: str
    depth: int
    nodes: list[EgoNode]
    edges: list[EgoEdge]
    truncated: bool
    indexing: bool
