"""`ghostbrain-api ontology-selfcheck`: proves the bundled JRE, Cypher and the
vector index work inside a frozen build (run by scripts/smoke-sidecar.py)."""
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path


def main() -> int:
    try:
        import arcadedb_embedded as arc  # noqa: PLC0415

        from ghostbrain.ontology.graph import GoldGraph  # noqa: PLC0415

        # The JVM keeps its log file open until process exit; on Windows that makes
        # cleanup fail, which must not turn a passing check into a FAIL.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            g = GoldGraph(Path(tmp) / "gold").open()
            with g.transaction():
                g.upsert_node("p", "Project", {"name": "selfcheck"})
                g.upsert_node("r", "Rule", {"name": "r", "value": "1"})
                assert g.upsert_edge("PART_OF", "r", "p", {})
            nodes, _, _ = g.neighbourhood("p", 1)
            assert {n["uid"] for n in nodes} == {"p", "r"}
            db = g._db
            db.schema.get_or_create_vertex_type("Probe")
            db.schema.get_or_create_property("Probe", "uid", arc.PropertyType.STRING)
            db.schema.get_or_create_property("Probe", "embedding", arc.PropertyType.ARRAY_OF_FLOATS)
            rng = random.Random(7)
            vecs = [[rng.random() for _ in range(8)] for _ in range(32)]
            with db.transaction():
                for i, v in enumerate(vecs):
                    vx = db.new_vertex("Probe")
                    vx.set("uid", f"v{i}")
                    vx.set("embedding", arc.to_java_float_array(v))
                    vx.save()
            idx = db.create_vector_index("Probe", "embedding", dimensions=8, id_property="uid")
            hits = idx.find_nearest(vecs[3], k=1)
            assert str(hits[0][0].get("uid")) == "v3"
            g.close()
    except Exception as e:  # noqa: BLE001
        print(f"ontology selfcheck: FAIL: {e}", file=sys.stderr)
        return 1
    print("ontology selfcheck: OK")
    return 0
