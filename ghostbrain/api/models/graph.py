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
