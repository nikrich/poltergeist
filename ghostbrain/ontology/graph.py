"""The gold graph: an embedded ArcadeDB database holding only ratified facts.

It is a projection of the ratification log (see projector.py) and can be
rebuilt from it at any time. Only the sidecar process may open it: ArcadeDB
embedded holds an exclusive per-process lock.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ghostbrain.ontology.schema import (
    DOMAIN_KINDS, EDGE_TYPES, META_UID, RELATION_TYPES, VERTEX_TYPES,
    check_edge, check_kind, check_prop,
)

DEFAULT_HEAP = "512m"
# Edges that place a node (project, evidence, scope) rather than relate it.
_STRUCTURAL_EDGES = ("PART_OF", "EVIDENCED_BY", "ABOUT", "IN", "WORKS_IN")
_jvm_lock = threading.Lock()


class GraphUnavailable(RuntimeError):
    """The gold graph cannot be opened (missing extra, JVM failure, corrupt store)."""


class GraphLocked(GraphUnavailable):
    """Another process holds the graph's lock."""


def _write_log_config(log_dir: Path) -> Path:
    """A java.util.logging config that keeps ArcadeDB's file log under log_dir.

    ArcadeDB's bundled config writes ./log/arcadedb.log relative to the process
    cwd, which in the packaged app may be read-only or the user's home.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    pattern = log_dir.resolve().as_posix().replace("%", "%%") + "/arcadedb.log"
    cfg = log_dir / "logging.properties"
    cfg.write_text(
        "handlers = java.util.logging.FileHandler\n"
        ".level = INFO\n"
        "java.util.logging.FileHandler.level = INFO\n"
        f"java.util.logging.FileHandler.pattern = {pattern}\n"
        "java.util.logging.FileHandler.formatter = com.arcadedb.log.LogFormatter\n"
        "java.util.logging.FileHandler.limit = 10000000\n"
        "java.util.logging.FileHandler.count = 3\n",
        encoding="utf-8",
    )
    return cfg


def _ensure_jvm(heap: str, log_dir: Path | None = None) -> None:
    import jpype  # noqa: PLC0415
    import jpype.config  # noqa: PLC0415
    from arcadedb_embedded import jvm  # noqa: PLC0415

    with _jvm_lock:
        if not jpype.isJVMStarted():
            jvm_args: list[str] = []
            if log_dir is not None:
                jvm_args.append(f"-Djava.util.logging.config.file={_write_log_config(log_dir)}")
                # JVM crash logs otherwise default to ./log/ as well.
                os.environ.setdefault("ARCADEDB_JVM_ERROR_FILE", str(log_dir / "hs_err_pid%p.log"))
            jvm.start_jvm(heap_size=heap, jvm_args=jvm_args or None)
            # The JVM is usually first started from a request-pool thread; JPype's
            # shutdown then waits on that attached thread forever and the process
            # never exits. Leave teardown to the OS (the service closes the DB at exit).
            jpype.config.destroy_jvm = False


def _set_clause(var: str, props: dict) -> tuple[str, dict]:
    parts, params = [], {}
    for key, value in props.items():
        if value is None:
            continue
        check_prop(key)
        parts.append(f"{var}.{key} = $p_{key}")
        params[f"p_{key}"] = value
    return (" SET " + ", ".join(parts)) if parts else "", params


class GoldGraph:
    def __init__(self, path: Path, heap: str | None = None) -> None:
        self._path = path
        self._heap = heap or os.environ.get("GHOSTBRAIN_ONTOLOGY_HEAP", DEFAULT_HEAP)
        self._db: Any = None

    # -- lifecycle -----------------------------------------------------------
    def open(self) -> "GoldGraph":
        try:
            import arcadedb_embedded as arc  # noqa: PLC0415
        except ImportError as e:
            raise GraphUnavailable("the ontology extra (arcadedb-embedded) is not installed") from e
        try:
            _ensure_jvm(self._heap, self._path.parent / "log")
        except Exception as e:  # noqa: BLE001 - surfaced as a status reason
            raise GraphUnavailable(f"could not start the JVM: {e}") from e
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if arc.database_exists(str(self._path)):
                self._db = arc.open_database(str(self._path))
            else:
                self._db = arc.create_database(str(self._path))
        except Exception as e:  # noqa: BLE001
            if "locked by another process" in str(e):
                raise GraphLocked(f"the gold graph is locked by another process ({self._path})") from e
            raise GraphUnavailable(f"could not open the gold graph: {e}") from e
        try:
            self._ensure_schema(arc)
        except Exception as e:  # noqa: BLE001 - release the lock so a later open can retry
            try:
                self.close()
            except Exception:  # noqa: BLE001
                self._db = None
            raise GraphUnavailable(f"could not prepare the gold graph schema: {e}") from e
        return self

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def _ensure_schema(self, arc: Any) -> None:
        schema = self._db.schema
        for t in VERTEX_TYPES:
            schema.get_or_create_vertex_type(t)
            schema.get_or_create_property(t, "uid", arc.PropertyType.STRING)
            schema.get_or_create_index(t, ["uid"], unique=True)
        for e in EDGE_TYPES:
            schema.get_or_create_edge_type(e)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._db.transaction():
            yield

    # -- primitives ------------------------------------------------------------
    def _rows(self, cypher: str, params: dict | None = None) -> list[dict]:
        rs = self._db.query("opencypher", cypher, params) if params else self._db.query("opencypher", cypher)
        return [{k: r.get(k) for k in r.get_property_names()} for r in rs]

    def _cmd(self, cypher: str, params: dict | None = None) -> list[dict]:
        rs = self._db.command("opencypher", cypher, params) if params else self._db.command("opencypher", cypher)
        if rs is None:
            return []
        return [{k: r.get(k) for k in r.get_property_names()} for r in rs]

    @staticmethod
    def _label(labels: Any) -> str:
        if isinstance(labels, str):
            return labels
        return list(labels)[0]

    # -- writes --------------------------------------------------------------
    def upsert_node(self, uid: str, kind: str, props: dict) -> None:
        check_kind(kind)
        existing = self._rows("MATCH (n) WHERE n.uid = $u RETURN labels(n) AS labels", {"u": uid})
        if existing and self._label(existing[0]["labels"]) != kind:
            self.set_props(uid, props)
            return
        set_sql, params = _set_clause("n", props)
        self._cmd(f"MERGE (n:{kind} {{uid: $uid}}){set_sql}", {"uid": uid, **params})

    def set_props(self, uid: str, props: dict) -> None:
        set_sql, params = _set_clause("n", props)
        if set_sql:
            self._cmd(f"MATCH (n) WHERE n.uid = $uid{set_sql}", {"uid": uid, **params})

    def upsert_edge(self, etype: str, src: str, dst: str, props: dict) -> bool:
        check_edge(etype)
        set_sql, params = _set_clause("e", props)
        rows = self._cmd(
            f"MATCH (a), (b) WHERE a.uid = $s AND b.uid = $d "
            f"MERGE (a)-[e:{etype}]->(b){set_sql} RETURN count(e) AS c",
            {"s": src, "d": dst, **params},
        )
        return bool(rows) and int(rows[0]["c"] or 0) > 0

    def delete_edge(self, etype: str, src: str, dst: str) -> None:
        check_edge(etype)
        self._cmd(f"MATCH (a)-[e:{etype}]->(b) WHERE a.uid = $s AND b.uid = $d DELETE e",
                  {"s": src, "d": dst})

    def delete_node(self, uid: str) -> None:
        self._cmd("MATCH (n) WHERE n.uid = $u DETACH DELETE n", {"u": uid})

    def clear(self) -> None:
        self._cmd("MATCH (n) DETACH DELETE n")

    def get_meta(self) -> int:
        rows = self._rows("MATCH (m:Meta) WHERE m.uid = $u RETURN m.last_applied_seq AS s", {"u": META_UID})
        return int(rows[0]["s"] or 0) if rows else 0

    def set_meta(self, seq: int) -> None:
        self._cmd("MERGE (m:Meta {uid: $u}) SET m.last_applied_seq = $s", {"u": META_UID, "s": seq})

    # -- reads ---------------------------------------------------------------
    def node(self, uid: str) -> dict | None:
        rows = self._rows(
            "MATCH (n) WHERE n.uid = $u RETURN labels(n) AS labels, n.name AS name, "
            "n.statement AS statement, n.value AS value, n.note_path AS note_path, "
            "n.provenance AS provenance, n.valid_from AS valid_from, n.ratification_id AS ratification_id",
            {"u": uid},
        )
        if not rows:
            return None
        row = rows[0]
        kind = self._label(row.pop("labels"))
        return {"uid": uid, "kind": kind, **row}

    def node_detail(self, uid: str) -> dict | None:
        """One node with its project, evidence and non-structural relations."""
        base = self.node(uid)
        if base is None:
            return None
        link = "ABOUT" if base["kind"] == "Artefact" else "PART_OF"
        proj = self._rows(
            f"MATCH (n)-[:{link}]->(p) WHERE n.uid = $u RETURN p.uid AS uid", {"u": uid})
        ev = self._rows(
            "MATCH (n)-[e:EVIDENCED_BY]->(a) WHERE n.uid = $u "
            "RETURN a.uid AS aid, a.note_path AS note_path, a.name AS title, "
            "e.quote AS quote, e.locator AS locator",
            {"u": uid},
        )
        skip = list(_STRUCTURAL_EDGES)
        rel_out = self._rows(
            "MATCH (n)-[e]->(m) WHERE n.uid = $u AND NOT type(e) IN $skip "
            "RETURN type(e) AS t, m.uid AS uid, m.name AS name, labels(m) AS labels",
            {"u": uid, "skip": skip},
        )
        rel_in = self._rows(
            "MATCH (m)-[e]->(n) WHERE n.uid = $u AND NOT type(e) IN $skip "
            "RETURN type(e) AS t, m.uid AS uid, m.name AS name, labels(m) AS labels",
            {"u": uid, "skip": skip},
        )
        relations = [
            {"direction": d, "type": r["t"], "uid": r["uid"], "name": r["name"] or r["uid"],
             "kind": self._label(r["labels"])}
            for d, rows in (("out", rel_out), ("in", rel_in)) for r in rows
        ]
        relations.sort(key=lambda r: (r["direction"], r["type"], r["uid"]))
        evidence = [
            {"aid": r["aid"], "note_path": r["note_path"], "title": r["title"] or r["aid"],
             "quote": r["quote"], "locator": r["locator"]}
            for r in ev
        ]
        evidence.sort(key=lambda r: (r["aid"], r["quote"] or "", r["locator"] or ""))
        return {**base, "project_uid": min((r["uid"] for r in proj), default=None),
                "evidence": evidence, "relations": relations}

    def neighbourhood(self, focus: str, depth: int, cap: int = 300) -> tuple[list[dict], list[dict], bool]:
        hops: dict[str, int] = {}
        if self.node(focus) is None:
            return [], [], False
        hops[focus] = 0
        frontier = [focus]
        edges: set[tuple[str, str, str]] = set()
        truncated = False
        for hop in range(1, depth + 1):
            if not frontier:
                break
            rows = self._rows(
                "MATCH (a)-[e]->(b) WHERE a.uid IN $u OR b.uid IN $u "
                "RETURN a.uid AS s, labels(a) AS sl, type(e) AS t, b.uid AS d, labels(b) AS dl",
                {"u": frontier},
            )
            kinds: dict[str, str] = {}
            for r in rows:
                for x, labels in ((r["s"], r["sl"]), (r["d"], r["dl"])):
                    if x not in hops:
                        kinds[x] = self._label(labels)
            # Domain (and other non-Artefact) nodes win the cap; among artefacts,
            # evidence of admitted domain nodes comes before mere bindings.
            domain = sorted(x for x, k in kinds.items() if k != "Artefact")
            room = max(cap - len(hops), 0)
            artefacts = [x for x, k in kinds.items() if k == "Artefact"]
            evidence_rows: list[dict] = []
            if artefacts and len(domain) + len(artefacts) > room:
                admitted = list(hops) + domain[:room]
                evidence_rows = [
                    {**r, "t": "EVIDENCED_BY"} for r in self._rows(
                        "MATCH (a)-[:EVIDENCED_BY]->(b) WHERE a.uid IN $s AND b.uid IN $d "
                        "RETURN a.uid AS s, b.uid AS d",
                        {"s": admitted, "d": artefacts},
                    )
                ]
            evidence = {r["d"] for r in evidence_rows}
            artefacts.sort(key=lambda x: (x not in evidence, x))
            nxt = (domain + artefacts)[:room]
            truncated = truncated or len(domain) + len(artefacts) > room
            for x in nxt:
                hops[x] = hop
            for r in rows + evidence_rows:
                if r["s"] in hops and r["d"] in hops:
                    edges.add((r["s"], r["t"], r["d"]))
            frontier = nxt
        info = self._rows(
            "MATCH (n) WHERE n.uid IN $u RETURN n.uid AS uid, labels(n) AS labels, "
            "n.name AS name, n.note_path AS note_path",
            {"u": list(hops)},
        )
        nodes = [
            {"uid": r["uid"], "kind": self._label(r["labels"]), "name": r["name"] or r["uid"],
             "note_path": r["note_path"], "hop": hops[r["uid"]]}
            for r in info
        ]
        nodes.sort(key=lambda n: (n["hop"], n["uid"]))
        return nodes, [{"src": s, "type": t, "dst": d} for s, t, d in sorted(edges)], truncated

    def domain_nodes(self, project_uid: str, limit: int = 500) -> list[dict]:
        rows = self._rows(
            "MATCH (n)-[:PART_OF]->(p) WHERE p.uid = $p RETURN n.uid AS uid, labels(n) AS labels, "
            "n.name AS name, n.statement AS statement, n.value AS value, "
            "n.valid_from AS valid_from, n.provenance AS provenance",
            {"p": project_uid},
        )
        out = [{"kind": self._label(r.pop("labels")), **r} for r in rows]
        out = [n for n in out if n["kind"] in DOMAIN_KINDS]
        out.sort(key=lambda n: n["uid"])
        return out[:limit]

    def project_export(self, project_uid: str) -> list[dict]:
        nodes = self.domain_nodes(project_uid)
        uids = [n["uid"] for n in nodes]
        if not uids:
            return []
        ev = self._rows(
            "MATCH (n)-[e:EVIDENCED_BY]->(a) WHERE n.uid IN $u "
            "RETURN n.uid AS uid, a.note_path AS note_path, a.name AS title, e.quote AS quote",
            {"u": uids},
        )
        rel = self._rows(
            "MATCH (n)-[e]->(m) WHERE n.uid IN $u AND type(e) IN $types "
            "RETURN n.uid AS uid, type(e) AS t, m.uid AS target, m.name AS target_name",
            {"u": uids, "types": list(RELATION_TYPES)},
        )
        by_uid = {n["uid"]: {**n, "evidence": [], "relations": []} for n in nodes}
        for r in sorted(ev, key=lambda r: (r["uid"], r["note_path"] or "", r["quote"] or "")):
            by_uid[r["uid"]]["evidence"].append(
                {"note_path": r["note_path"], "title": r["title"], "quote": r["quote"]})
        for r in sorted(rel, key=lambda r: (r["uid"], r["t"], r["target"])):
            by_uid[r["uid"]]["relations"].append(
                {"type": r["t"], "target_uid": r["target"], "target_name": r["target_name"]})
        return [by_uid[u] for u in sorted(by_uid)]

    def snapshot(self) -> dict:
        nodes = self._rows(
            "MATCH (n) WHERE NOT n:Meta RETURN n.uid AS uid, labels(n) AS labels, n.name AS name, "
            "n.statement AS statement, n.value AS value, n.note_path AS note_path, "
            "n.provenance AS provenance, n.ratification_id AS ratification_id, n.valid_from AS valid_from"
        )
        for n in nodes:
            n["kind"] = self._label(n.pop("labels"))
        edges = self._rows(
            "MATCH (a)-[e]->(b) RETURN a.uid AS src, type(e) AS type, b.uid AS dst, "
            "e.quote AS quote, e.locator AS locator"
        )
        return {
            "nodes": sorted(nodes, key=lambda n: n["uid"]),
            "edges": sorted(edges, key=lambda e: (e["src"], e["type"], e["dst"], e["quote"] or "")),
        }
