import time

from ghostbrain.ontology import pipeline, service as service_mod


class FakeEmbedder:
    def encode(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 64
            for w in t.lower().split():
                v[hash(w) % 64] += 1.0
            out.append(v)
        return out


class _Res:
    def __init__(self, items):
        self._items = items

    def as_json(self):
        return {"items": self._items}


def _note(vault, rel, aid, body):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nid: {aid}\ntitle: {aid}\ncreated: 2026-0{aid[-1]}-01\n---\n{body}\n", encoding="utf-8")


def _llm(prompt, **kw):
    if "day 31" in prompt:
        return _Res([{"kind": "Rule", "name": "lapse day", "statement": "Today lapse is day 31.", "value": "31",
                      "existing_uid": None, "relations": [], "quote": "lapse is day 31", "locator": "",
                      "confidence": 0.7, "topic": ""}])
    return _Res([])


def _bind(svc, project, refs):
    for aid, path in refs:
        svc.store.upsert_binding(project, aid, path, aid, "bound")


def test_run_extraction_processes_oldest_first_and_is_idempotent(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    _note(tmp_vault, "20-contexts/work/a2.md", "a2", "Agreed: lapse is day 31.")
    _note(tmp_vault, "20-contexts/work/a1.md", "a1", "Kickoff notes, nothing settled.")
    _bind(svc, "p1", [("a1", "20-contexts/work/a1.md"), ("a2", "20-contexts/work/a2.md")])
    out = pipeline.run_extraction(svc, "p1", limit=1, run=_llm, embedder=FakeEmbedder())
    assert out["processed"] == 1 and out["new"] == 0          # a1 (oldest) first
    out = pipeline.run_extraction(svc, "p1", limit=25, run=_llm, embedder=FakeEmbedder())
    assert out["processed"] == 1 and out["new"] == 1 and out["skipped"] == 1
    out = pipeline.run_extraction(svc, "p1", limit=25, run=_llm, embedder=FakeEmbedder())
    assert out["processed"] == 0 and out["skipped"] == 2


def test_missing_source_is_recorded_and_run_continues(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    _note(tmp_vault, "20-contexts/work/a2.md", "a2", "Agreed: lapse is day 31.")
    _bind(svc, "p1", [("a1", "20-contexts/work/gone.md"), ("a2", "20-contexts/work/a2.md")])
    out = pipeline.run_extraction(svc, "p1", run=_llm, embedder=FakeEmbedder())
    assert out["failed"] == 1 and out["new"] == 1


def test_consecutive_failures_stop_the_run(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    refs = []
    for i in range(1, 8):
        _note(tmp_vault, f"20-contexts/work/n{i}.md", f"n{i}", "text")
        refs.append((f"n{i}", f"20-contexts/work/n{i}.md"))
    _bind(svc, "p1", refs)
    out = pipeline.run_extraction(svc, "p1", run=lambda p, **kw: _Res("bad"), embedder=FakeEmbedder())
    assert out["failed"] == pipeline.MAX_CONSECUTIVE_FAILURES
    assert "consecutive" in out["stopped"]


def test_runner_reports_status(ontology_root, tmp_vault, monkeypatch):
    svc = service_mod.get_service()
    monkeypatch.setattr(pipeline, "run_extraction",
                        lambda s, p, limit=25, **kw: {"processed": 0, "stopped": None})
    runner = pipeline.get_runner(svc)
    assert runner.start("p1", 5) is True
    for _ in range(50):
        if not runner.status()["running"]:
            break
        time.sleep(0.02)
    st = runner.status()
    assert st["running"] is False and st["summary"] == {"processed": 0, "stopped": None}


def test_get_runner_is_atomic_under_concurrent_first_calls(monkeypatch):
    import threading
    import types

    real_init = pipeline.ExtractionRunner.__init__

    def slow_init(self, svc):
        time.sleep(0.05)  # widen the check-then-set window
        real_init(self, svc)

    monkeypatch.setattr(pipeline.ExtractionRunner, "__init__", slow_init)
    svc = types.SimpleNamespace(extraction=None)
    got, barrier = [], threading.Barrier(8)

    def call():
        barrier.wait()
        got.append(pipeline.get_runner(svc))

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(got) == 8 and all(r is svc.extraction for r in got)


def test_pipeline_passes_project_name_and_seeds_to_extract(ontology_root, tmp_vault, monkeypatch):
    svc = service_mod.get_service()
    _note(tmp_vault, "20-contexts/work/a1.md", "a1", "Orbit notes.")
    _bind(svc, "p1", [("a1", "20-contexts/work/a1.md")])
    monkeypatch.setattr(svc.store, "project_seeds", lambda uuid: ["Orbit", "OBT"])
    monkeypatch.setattr(pipeline.projects_repo, "get_project_by_uuid", lambda uuid: {"name": "Orbit"})
    seen = []

    def spy(title, text, digest, **kw):
        seen.append(kw)
        return [], 0

    monkeypatch.setattr(pipeline.extract, "extract_chunk", spy)
    pipeline.run_extraction(svc, "p1", embedder=FakeEmbedder())
    assert [{k: v for k, v in s.items() if k != "topics"} for s in seen] == [
        {"run": None, "project_name": "Orbit", "seeds": ["Orbit", "OBT"]}]
    assert [t["name"] for t in seen[0]["topics"]] == ["Orbit"]


def test_extraction_respects_topic_boundary(ontology_root, tmp_vault, monkeypatch):
    from ghostbrain.api.repo import projects
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    out_t = svc.store.ensure_topic(p["uuid"], "claims triage")
    svc.store.set_topic_status(out_t["uid"], "out")
    _note(tmp_vault, "20-contexts/work/a1.md", "a1", "Orbit core fact day 31. Claims triage fact day 9. Billing fact day 5.")
    _bind(svc, p["uuid"], [("a1", "20-contexts/work/a1.md")])

    def run(prompt, **kw):
        mk = lambda topic, q: {"kind": "Rule", "name": topic, "statement": f"Today {q}.", "value": None,
                                "existing_uid": None, "relations": [], "quote": q, "locator": "",
                                "confidence": 0.7, "topic": topic}
        return _Res([mk("Orbit", "Orbit core fact day 31"), mk("claims triage", "Claims triage fact day 9"),
                     mk("billing", "Billing fact day 5")])
    out = pipeline.run_extraction(svc, p["uuid"], run=run, embedder=FakeEmbedder())
    assert (out["new"], out["out_of_scope"], out["waiting"]) == (1, 1, 1)
    billing = svc.store.ensure_topic(p["uuid"], "billing")
    item = svc.store.open_scope_item(p["uuid"], billing["uid"])
    assert item and item["payload"]["notes"][0]["aid"] == "a1"
    waiting = svc.store.candidates_for_topic(p["uuid"], billing["uid"], "waiting_scope")
    assert len(waiting) == 1
    assert not [i for i in svc.store.open_items(p["uuid"]) if i["candidate_id"] == waiting[0]["id"]]
    assert svc.store.candidates_for_topic(p["uuid"], out_t["uid"], "pending") == []
    assert svc.store.candidates_for_topic(p["uuid"], out_t["uid"], "waiting_scope") == []


def _fact(topic, q):
    return {"kind": "Rule", "name": q, "statement": f"Today {q}.", "value": None, "existing_uid": None,
            "relations": [], "quote": q, "locator": "", "confidence": 0.7, "topic": topic}


def test_two_notes_share_one_scope_item(ontology_root, tmp_vault):
    from ghostbrain.api.repo import projects
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    _note(tmp_vault, "20-contexts/work/a1.md", "a1", "Billing runs nightly at two.")
    _note(tmp_vault, "20-contexts/work/a2.md", "a2", "Billing invoices are sent monthly.")
    _bind(svc, p["uuid"], [("a1", "20-contexts/work/a1.md"), ("a2", "20-contexts/work/a2.md")])

    def run(prompt, **kw):
        q = "Billing runs nightly at two" if "nightly" in prompt else "Billing invoices are sent monthly"
        return _Res([_fact("billing", q)])
    out = pipeline.run_extraction(svc, p["uuid"], run=run, embedder=FakeEmbedder())
    assert out["waiting"] == 2
    billing = svc.store.ensure_topic(p["uuid"], "billing")
    scope_items = [i for i in svc.store.open_items(p["uuid"]) if i["type"] == "scope"]
    assert len(scope_items) == 1
    assert {n["aid"] for n in scope_items[0]["payload"]["notes"]} == {"a1", "a2"}
    assert len(svc.store.candidates_for_topic(p["uuid"], billing["uid"], "waiting_scope")) == 2
    # asking again for the same note never duplicates it
    b = svc.store.bindings(p["uuid"], "bound")[0]
    pipeline._ask_scope(svc, p["uuid"], billing, b)
    item = svc.store.open_scope_item(p["uuid"], billing["uid"])
    assert len(item["payload"]["notes"]) == 2


def test_unclassified_and_empty_labels_route_to_core(ontology_root, tmp_vault):
    from ghostbrain.api.repo import projects
    from ghostbrain.ontology import onboarding, topics as topics_mod
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    _note(tmp_vault, "20-contexts/work/a1.md", "a1", "Orbit core fact day 31. Orbit other fact day 9.")
    _bind(svc, p["uuid"], [("a1", "20-contexts/work/a1.md")])
    svc.store.ensure_topic(p["uuid"], topics_mod.UNCLASSIFIED)
    prompts = []

    def run(prompt, **kw):
        prompts.append(prompt)
        return _Res([_fact("Unclassified", "Orbit core fact day 31"), _fact("", "Orbit other fact day 9")])
    out = pipeline.run_extraction(svc, p["uuid"], run=run, embedder=FakeEmbedder())
    core = onboarding.core_topic(svc, p["uuid"])
    assert (out["new"], out["waiting"]) == (2, 0)
    assert len(svc.store.candidates_for_topic(p["uuid"], core["uid"], "pending")) == 2
    assert "- unclassified" not in prompts[0].lower()
    assert not [i for i in svc.store.open_items(p["uuid"]) if i["type"] == "scope"]


def test_extraction_raised_note_survives_a_no(ontology_root, tmp_vault):
    import pytest
    pytest.importorskip("arcadedb_embedded")
    from ghostbrain.api.repo import projects
    from ghostbrain.ontology import backlog
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    svc.seed()
    rel = "20-contexts/work/projects/orbit/a1.md"
    _note(tmp_vault, rel, "a1", "Orbit kickoff. Billing runs nightly at two.")
    svc.commit("bind", {"project": p["uuid"], "artefacts": [{"aid": "a1", "path": rel, "title": "a1"}]})
    _bind(svc, p["uuid"], [("a1", rel)])

    def run(prompt, **kw):
        return _Res([_fact("billing", "Billing runs nightly at two")])
    pipeline.run_extraction(svc, p["uuid"], run=run, embedder=FakeEmbedder())
    billing = svc.store.ensure_topic(p["uuid"], "billing")
    item = svc.store.open_scope_item(p["uuid"], billing["uid"])
    assert item["payload"]["notes"][0]["raised_by"] == "extraction"
    [waiting] = svc.store.candidates_for_topic(p["uuid"], billing["uid"], "waiting_scope")
    backlog.act(svc, item["id"], "no")
    assert svc.store.topic(billing["uid"])["status"] == "out"
    assert svc.store.candidate(waiting["id"])["status"] == "rejected"
    assert [b["status"] for b in svc.store.bindings(p["uuid"])] == ["bound"]
    assert svc.store.events()[-1].payload["excluded"] == []
    with svc.graph_session() as g:
        edges = g.snapshot()["edges"]
    assert {"src": "a1", "type": "ABOUT", "dst": p["uuid"], "quote": None, "locator": None} in edges
