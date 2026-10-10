"""Triage of validated candidates (M1: duplicates and rejection memory).
Contradiction, equivalence and re-opened items arrive in milestone 2."""
from __future__ import annotations

import math
from array import array
from collections.abc import Sequence
from typing import Protocol

from ghostbrain.ontology.extract import EXTRACTOR_VERSION, CandidateIn

TAU_DUP = 0.92
TAU_REJ = 0.90


class TriageUnavailable(RuntimeError):
    pass


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> Sequence[Sequence[float]]: ...


def default_embedder() -> Embedder:
    """The same MiniLM model the semantic index uses (packaged sidecar ships it)."""
    try:
        from ghostbrain.api.repo.search import _get_embedder
        from ghostbrain.semantic.index import DEFAULT_MODEL_NAME
        return _get_embedder(DEFAULT_MODEL_NAME)
    except Exception as e:
        raise TriageUnavailable(f"embedding model unavailable: {e}") from e


def canonical(c: CandidateIn) -> str:
    return f"{c.kind} {c.name}: {c.statement} {c.value or ''}".strip()


def pack(vec: Sequence[float]) -> bytes:
    return array("f", [float(x) for x in vec]).tobytes()


def unpack(blob: bytes) -> list[float]:
    a = array("f")
    a.frombytes(blob)
    return list(a)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _norm_value(v: str | None) -> str | None:
    return (v or "").strip() or None


def _best(store, project_uuid: str, status: str, kind: str, vec: list[float],
          value: str | None) -> tuple[float, dict | None]:
    """Best-scoring candidate of this kind and normalised value; value mismatches never match."""
    best, best_row = 0.0, None
    for row in store.candidates(project_uuid, status):
        if (row["kind"] != kind or row["embedding"] is None
                or _norm_value(row["value"]) != _norm_value(value)):
            continue
        score = cosine(vec, unpack(row["embedding"]))
        if score > best:
            best, best_row = score, row
    return best, best_row


def _merge(store, dup: dict, evidence: list[dict], confidence: float) -> None:
    """Fold a duplicate's evidence into `dup`; new sources raise its confidence."""
    seen = {e["aid"] for e in store.evidence(dup["id"])}
    combined = dup["confidence"]
    new_source = False
    for e in evidence:
        if e["aid"] in seen:
            continue
        seen.add(e["aid"])
        new_source = True
        store.add_evidence(dup["id"], e["aid"], e["quote"], e["locator"])
    combined = 1 - (1 - combined) * (1 - confidence) if new_source else max(combined, confidence)
    store.set_candidate_confidence(dup["id"], combined)


def triage(store, project_uuid: str, aid: str, c: CandidateIn, embedder: Embedder, *,
           topic_uid: str | None = None, status: str = "pending") -> tuple[str, int | None]:
    vec = [float(x) for x in embedder.encode([canonical(c)])[0]]
    if status == "waiting_scope":
        cid = store.add_candidate(
            project_uuid, kind=c.kind, name=c.name, statement=c.statement, value=c.value,
            existing_uid=c.existing_uid, relations=c.relations, confidence=c.confidence,
            extractor_version=EXTRACTOR_VERSION, embedding=pack(vec),
            topic_uid=topic_uid, status="waiting_scope",
        )
        store.add_evidence(cid, aid, c.quote, c.locator)
        return "waiting", cid
    rej_score, _ = _best(store, project_uuid, "rejected", c.kind, vec, c.value)
    if rej_score >= TAU_REJ:
        return "dropped", None
    dup_score, dup = _best(store, project_uuid, "pending", c.kind, vec, c.value)
    if dup is not None and dup_score >= TAU_DUP:
        _merge(store, dup, [{"aid": aid, "quote": c.quote, "locator": c.locator}], c.confidence)
        return "merged", dup["id"]
    cid = store.add_candidate(
        project_uuid, kind=c.kind, name=c.name, statement=c.statement, value=c.value,
        existing_uid=c.existing_uid, relations=c.relations, confidence=c.confidence,
        extractor_version=EXTRACTOR_VERSION, embedding=pack(vec), topic_uid=topic_uid,
    )
    store.add_evidence(cid, aid, c.quote, c.locator)
    store.add_item(project_uuid, "candidate", candidate_id=cid)
    return "new", cid


def release_waiting(store, project_uuid: str, cid: int) -> str:
    """Release a candidate held for a scope answer through the normal triage.

    Near a rejected fact it is dropped; near a pending one it is merged into it; otherwise it
    becomes pending with its own backlog item. Returns "dropped", "merged" or "new".
    """
    c = store.candidate(cid)
    if c["embedding"] is not None:
        vec = unpack(c["embedding"])
        rej_score, _ = _best(store, project_uuid, "rejected", c["kind"], vec, c["value"])
        if rej_score >= TAU_REJ:
            store.set_candidate_status(cid, "dropped")
            return "dropped"
        dup_score, dup = _best(store, project_uuid, "pending", c["kind"], vec, c["value"])
        if dup is not None and dup_score >= TAU_DUP:
            _merge(store, dup, store.evidence(cid), c["confidence"])
            store.set_candidate_status(cid, "merged")
            return "merged"
    store.set_candidate_status(cid, "pending")
    store.add_item(project_uuid, "candidate", candidate_id=cid)
    return "new"
