"""Process-wide ontology service owned by the sidecar.

The log (SQLite) is truth. The gold graph is opened lazily, on first use, which
also starts the JVM, and is caught up from the log whenever it is opened or
after each commit.
"""
from __future__ import annotations

import atexit
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from ghostbrain import paths
from ghostbrain.ontology import identity, projector
from ghostbrain.ontology.graph import GoldGraph, GraphUnavailable
from ghostbrain.ontology.store import Store

log = logging.getLogger(__name__)

_PROJECT_KEYS = ("project",)


class OntologyService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = Store(root / "ontology.db")
        self._graph: GoldGraph | None = None
        self._lock = threading.RLock()
        self.on_applied: list[Callable[["OntologyService", list[str]], None]] = []
        self.extraction = None  # set by pipeline.ExtractionRunner (Task 10)

    # -- graph ---------------------------------------------------------------
    def _sync(self) -> tuple[GoldGraph, list]:
        """Open the graph if needed and catch it up; return it with the events applied."""
        g = self._graph
        opened_here = g is None
        if g is None:
            g = GoldGraph(self.root / "gold")
            g.open()
        try:
            events = self.store.events(after=g.get_meta())
            projector.catch_up(self.store, g)
        except Exception:
            if opened_here:
                self._close_quietly(g)
            raise
        self._graph = g
        return g, events

    @staticmethod
    def _close_quietly(g: GoldGraph) -> None:
        try:
            g.close()
        except Exception:  # noqa: BLE001
            log.exception("ontology: closing the graph failed")

    def _drop_graph(self) -> None:
        g, self._graph = self._graph, None
        if g is not None:
            self._close_quietly(g)

    @contextmanager
    def graph_session(self) -> Iterator[GoldGraph]:
        with self._lock:
            yield self._sync()[0]

    def status(self) -> dict:
        try:
            with self.graph_session():
                pass
            return {"available": True, "reason": None}
        except GraphUnavailable as e:
            return {"available": False, "reason": str(e)}

    # -- writes --------------------------------------------------------------
    def commit(self, type: str, payload: dict, actor: str = "user") -> int:
        """Append to the log (truth), then try to project. Never raises after the append."""
        with self._lock:
            seq = self.store.append_event(type, payload, actor)
            try:
                _, events = self._sync()
                self._notify(sorted({e.payload[k] for e in events for k in _PROJECT_KEYS if k in e.payload}))
            except GraphUnavailable as e:
                log.warning("ontology: committed seq %s but the graph is unavailable: %s", seq, e)
            except Exception:  # noqa: BLE001 - the log is truth; the graph catches up on next open
                log.exception("ontology: committed seq %s but projecting it failed", seq)
                self._drop_graph()
            return seq

    def _notify(self, project_uuids: list[str]) -> None:
        for hook in list(self.on_applied):
            try:
                hook(self, project_uuids)
            except Exception:  # noqa: BLE001 - a projection failure must not undo a commit
                log.exception("ontology: on_applied hook failed")

    def rebuild(self) -> int:
        with self._lock:
            g, _ = self._sync()
            n = projector.rebuild(self.store, g)
            self._notify([p["project_uuid"] for p in self.store.enabled_projects()])
            return n

    def seed(self) -> int:
        return self.commit("seed", identity.seed_payload(self.store), actor="system")

    def close(self) -> None:
        with self._lock:
            if self._graph is not None:
                self._graph.close()
                self._graph = None
            self.store.close()


_service: OntologyService | None = None
_service_lock = threading.Lock()


def get_service() -> OntologyService:
    global _service
    with _service_lock:
        if _service is None:
            _service = OntologyService(paths.ontology_dir())
            from ghostbrain.ontology import projection_md  # noqa: PLC0415  (Task 12)
            _service.on_applied.append(projection_md.on_applied)
        return _service


def reset_service() -> None:
    global _service
    with _service_lock:
        if _service is not None:
            _service.close()
            _service = None


atexit.register(reset_service)
