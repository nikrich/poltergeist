"""Allowlists for the gold graph. Anything interpolated into Cypher comes from here."""
from __future__ import annotations

import re

CORE_KINDS: tuple[str, ...] = ("Self", "Context", "Project", "Artefact", "Topic")
DOMAIN_KINDS: tuple[str, ...] = (
    "Concept", "Rule", "Decision", "Requirement", "System", "Role", "OpenQuestion",
)
VERTEX_TYPES: tuple[str, ...] = CORE_KINDS + DOMAIN_KINDS + ("Meta",)

BINDING_EDGES: tuple[str, ...] = ("WORKS_IN", "IN", "ABOUT", "RECORDED_IN", "IN_SCOPE", "OUT_OF_SCOPE", "HAS_TOPIC")
DOMAIN_EDGES: tuple[str, ...] = (
    "PART_OF", "DEFINES", "CONSTRAINS", "DEPENDS_ON", "SUPERSEDES",
    "SAME_AS", "SCOPED_EXCEPTION", "EVIDENCED_BY",
)
EDGE_TYPES: tuple[str, ...] = BINDING_EDGES + DOMAIN_EDGES
# Relations the extractor may propose between domain nodes.
RELATION_TYPES: tuple[str, ...] = ("DEFINES", "CONSTRAINS", "DEPENDS_ON", "SUPERSEDES")

PROVENANCE: tuple[str, ...] = ("observed", "extracted", "answered", "seeded")
EVENT_TYPES: tuple[str, ...] = (
    "seed", "bind", "ratify", "reject", "by_design", "investigate", "revert", "relabel", "scope",
)

SELF_UID = "self"
META_UID = "meta"

_UI_KIND = {"OpenQuestion": "question"}
_PROP_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def ui_kind(kind: str) -> str:
    """The lowercase kind the desktop graph colours by."""
    return _UI_KIND.get(kind, kind.lower())


def check_kind(kind: str) -> str:
    if kind not in VERTEX_TYPES:
        raise ValueError(f"unknown vertex type: {kind!r}")
    return kind


def check_edge(etype: str) -> str:
    if etype not in EDGE_TYPES:
        raise ValueError(f"unknown edge type: {etype!r}")
    return etype


def check_prop(name: str) -> str:
    if not _PROP_RE.match(name):
        raise ValueError(f"invalid property name: {name!r}")
    return name
