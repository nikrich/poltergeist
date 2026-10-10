"""Run extraction over a project's bound artefacts, oldest first. Idempotent on
(content hash, extractor version). M1 runs on demand; milestone 2 schedules it."""
from __future__ import annotations

import hashlib
import logging
import threading

from ghostbrain.api.repo import projects as projects_repo
from ghostbrain.ontology import extract, scope, triage
from ghostbrain.ontology import topics as topics_mod
from ghostbrain.ontology.graph import GraphUnavailable
from ghostbrain.ontology.store import norm_topic as store_norm

log = logging.getLogger(__name__)
MAX_CONSECUTIVE_FAILURES = 5
DIGEST_LIMIT = 150


def _digest(svc, project_uuid: str) -> list[dict]:
    try:
        with svc.graph_session() as g:
            return g.domain_nodes(project_uuid, limit=DIGEST_LIMIT)
    except GraphUnavailable:
        return []


def _ordered_bound(svc, project_uuid: str) -> list[tuple[dict, tuple[dict, str] | None]]:
    rows = []
    for b in svc.store.bindings(project_uuid, "bound"):
        loaded = scope.read_artefact(b["path"])
        created = str((loaded[0] if loaded else {}).get("created") or "9999")
        rows.append((created, b, loaded))
    rows.sort(key=lambda r: (r[0], r[1]["path"]))
    return [(b, loaded) for _, b, loaded in rows]


def _ask_scope(svc, project_uuid: str, topic: dict, b: dict) -> None:
    """Raise (or extend) the scope question for a topic that extraction surfaced."""
    entry = {"aid": b["aid"], "path": b["path"], "title": b["title"], "reason": "raised by extraction",
             "raised_by": "extraction"}
    existing = svc.store.open_scope_item(project_uuid, topic["uid"])
    if existing:
        payload = existing["payload"]
        notes = payload.get("notes", [])
        if all(n["aid"] != b["aid"] for n in notes):
            payload["notes"] = notes + [entry]
            svc.store.update_item_payload(existing["id"], payload)
        return
    svc.store.add_item(project_uuid, "scope", payload={
        "topic_uid": topic["uid"], "name": topic["name"], "lean": "unclear", "notes": [entry]})


def run_extraction(svc, project_uuid: str, *, limit: int = 25, run=None, embedder=None) -> dict:
    out = {"processed": 0, "new": 0, "merged": 0, "dropped": 0, "discarded": 0,
           "failed": 0, "skipped": 0, "out_of_scope": 0, "waiting": 0, "stopped": None}
    from ghostbrain.ontology import onboarding  # local import: onboarding imports this package
    embedder = embedder or triage.default_embedder()
    digest = _digest(svc, project_uuid)
    project = projects_repo.get_project_by_uuid(project_uuid) or {}
    project_name = str(project.get("name") or "")
    seeds = svc.store.project_seeds(project_uuid) or []
    core = onboarding.core_topic(svc, project_uuid)
    topics_rows = [t for t in svc.store.topics(project_uuid) if t["name"] != topics_mod.UNCLASSIFIED]
    consecutive = 0
    for b, loaded in _ordered_bound(svc, project_uuid):
        if out["processed"] + out["failed"] >= limit:
            break
        if loaded is None:
            svc.store.record_extraction(project_uuid, b["aid"], "missing", extract.EXTRACTOR_VERSION,
                                        "failed", "source missing")
            out["failed"] += 1
            continue
        meta, body = loaded
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if svc.store.extraction_done(project_uuid, b["aid"], content_hash, extract.EXTRACTOR_VERSION):
            out["skipped"] += 1
            continue
        try:
            for chunk in extract.chunk_text(body):
                candidates, discarded = extract.extract_chunk(
                    b["title"], chunk, digest, run=run, project_name=project_name, seeds=seeds,
                    topics=topics_rows)
                out["discarded"] += discarded
                for c in candidates:
                    label = c.topic.strip()
                    if not label or store_norm(label) == store_norm(topics_mod.UNCLASSIFIED):
                        label = core["name"]   # reserved bucket is never an LLM label
                    t = svc.store.ensure_topic(project_uuid, label)
                    if t["status"] == "out":
                        out["out_of_scope"] += 1
                        continue
                    if t["status"] == "pending":
                        _ask_scope(svc, project_uuid, t, b)
                        kind, _ = triage.triage(svc.store, project_uuid, b["aid"], c, embedder,
                                                topic_uid=t["uid"], status="waiting_scope")
                        out["waiting"] += 1
                        continue
                    kind, _ = triage.triage(svc.store, project_uuid, b["aid"], c, embedder,
                                            topic_uid=t["uid"])
                    out[kind] += 1
        except extract.ExtractionFailed as e:
            svc.store.record_extraction(project_uuid, b["aid"], content_hash, extract.EXTRACTOR_VERSION,
                                        "failed", str(e))
            out["failed"] += 1
            consecutive += 1
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                out["stopped"] = f"stopped after {consecutive} consecutive failures: {e}"
                break
            continue
        consecutive = 0
        svc.store.record_extraction(project_uuid, b["aid"], content_hash, extract.EXTRACTOR_VERSION, "ok")
        out["processed"] += 1
    return out


class ExtractionRunner:
    def __init__(self, svc) -> None:
        self._svc = svc
        self._lock = threading.Lock()
        self._state = {"running": False, "project": None, "summary": None, "last_error": None}

    def start(self, project_uuid: str, limit: int) -> bool:
        with self._lock:
            if self._state["running"]:
                return False
            self._state = {"running": True, "project": project_uuid, "summary": None, "last_error": None}
        threading.Thread(target=self._run, args=(project_uuid, limit), daemon=True,
                         name="ontology-extract").start()
        return True

    def _run(self, project_uuid: str, limit: int) -> None:
        summary, error = None, None
        try:
            summary = run_extraction(self._svc, project_uuid, limit=limit)
            error = summary.get("stopped")
        except Exception as e:  # noqa: BLE001 - surfaced through status()
            log.exception("ontology extraction failed")
            error = str(e)
        with self._lock:
            self._state = {"running": False, "project": project_uuid, "summary": summary, "last_error": error}

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)


_runner_lock = threading.Lock()


def get_runner(svc) -> ExtractionRunner:
    with _runner_lock:  # concurrent first calls must not create two runners
        if svc.extraction is None:
            svc.extraction = ExtractionRunner(svc)
        return svc.extraction
