import pytest

from ghostbrain.api.repo import projects
from ghostbrain.ontology import pipeline, service as service_mod
from ghostbrain.ontology.graph import GoldGraph, GraphLocked


def _note(vault, rel, aid, body):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nid: {aid}\ntitle: {aid}\n---\n{body}\n", encoding="utf-8")


def test_status_and_graph_503_when_locked(ontology_root, client, auth_headers, monkeypatch):
    monkeypatch.setattr(GoldGraph, "open", lambda self: (_ for _ in ()).throw(GraphLocked("locked by another process")))
    r = client.get("/v1/ontology/status", headers=auth_headers)
    assert r.json() == {"available": False, "reason": "locked by another process"}
    r = client.get("/v1/ontology/graph", params={"project": "x"}, headers=auth_headers)
    assert r.status_code == 503 and "locked" in r.json()["detail"]


def test_enable_scope_ratify_binding_and_graph(ontology_root, tmp_vault, client, auth_headers):
    pytest.importorskip("arcadedb_embedded")
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/jira/t1.md", "t1", "Orbit lapse is day 31. Orbit rules. Orbit team.")
    r = client.post("/v1/ontology/projects/enable", json={"project_id": p["id"], "seeds": ["Orbit"]},
                    headers=auth_headers)
    assert r.status_code == 200 and r.json()["uuid"] == p["uuid"]
    items = client.get("/v1/ontology/backlog", params={"project": p["uuid"]}, headers=auth_headers).json()
    assert items[0]["type"] == "binding" and items[0]["artefacts"][0]["aid"] == "t1"
    r = client.post(f"/v1/ontology/backlog/{items[0]['id']}/action", json={"action": "ratify"}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["ok"] is True
    r = client.post(f"/v1/ontology/backlog/{items[0]['id']}/action", json={"action": "ratify"}, headers=auth_headers)
    assert r.status_code == 409
    g = client.get("/v1/ontology/graph", params={"project": p["uuid"], "depth": 2}, headers=auth_headers).json()
    kinds = {n["path"]: n["kind"] for n in g["nodes"]}
    assert g["focus"] == p["uuid"] and kinds[p["uuid"]] == "project" and kinds["t1"] == "artefact"
    art = next(n for n in g["nodes"] if n["path"] == "t1")
    assert art["note_path"] == "20-contexts/work/jira/t1.md"
    assert {"source": "t1", "target": p["uuid"], "weight": 1.0, "kind": "about"} in g["edges"]
    listed = client.get("/v1/ontology/projects", headers=auth_headers).json()
    assert listed[0]["bound"] == 1 and listed[0]["seeds"] == ["Orbit"]


def test_enable_unknown_project_422_and_empty_seeds_422(ontology_root, tmp_vault, client, auth_headers):
    r = client.post("/v1/ontology/projects/enable", json={"project_id": "work/nope", "seeds": ["x"]}, headers=auth_headers)
    assert r.status_code == 422
    p = projects.create_project("work", "Orbit")
    r = client.post("/v1/ontology/projects/enable", json={"project_id": p["id"], "seeds": []}, headers=auth_headers)
    assert r.status_code == 422


def test_extract_start_conflict(ontology_root, tmp_vault, client, auth_headers, monkeypatch):
    svc = service_mod.get_service()
    svc.store.enable_project("p1", ["x"])
    runner = pipeline.get_runner(svc)
    monkeypatch.setattr(runner, "start", lambda project, limit: False)
    r = client.post("/v1/ontology/projects/p1/extract", json={"limit": 5}, headers=auth_headers)
    assert r.status_code == 409


def test_bad_action_422_and_missing_item_404(ontology_root, tmp_vault, client, auth_headers):
    r = client.post("/v1/ontology/backlog/999/action", json={"action": "ratify"}, headers=auth_headers)
    assert r.status_code == 404
    r = client.post("/v1/ontology/backlog/999/action", json={"action": "explode"}, headers=auth_headers)
    assert r.status_code == 422


def test_revert_only_domain_nodes(ontology_root, tmp_vault, client, auth_headers):
    pytest.importorskip("arcadedb_embedded")
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/jira/t1.md", "t1", "Orbit lapse is day 31. Orbit rules. Orbit team.")
    client.post("/v1/ontology/projects/enable", json={"project_id": p["id"], "seeds": ["Orbit"]}, headers=auth_headers)
    item = client.get("/v1/ontology/backlog", params={"project": p["uuid"]}, headers=auth_headers).json()[0]
    client.post(f"/v1/ontology/backlog/{item['id']}/action", json={"action": "ratify"}, headers=auth_headers)
    svc = service_mod.get_service()
    svc.commit("ratify", {
        "project": p["uuid"], "provenance": "extracted", "extractor_version": "test",
        "node": {"uid": "r1", "kind": "Rule", "name": "lapse day", "statement": "Lapse on day 31.", "value": "31"},
    })
    for core in (p["uuid"], "t1", "self"):
        r = client.post(f"/v1/ontology/nodes/{core}/revert", json={"project": p["uuid"]}, headers=auth_headers)
        assert r.status_code == 422, core
    r = client.post("/v1/ontology/nodes/r1/revert", json={"project": p["uuid"]}, headers=auth_headers)
    assert r.status_code == 200
    with svc.graph_session() as g:
        assert g.node("r1") is None and g.node("t1") is not None


def _ratify_node(svc, project, uid, kind, name, statement, evidence=(), relations=()):
    svc.commit("ratify", {
        "project": project, "provenance": "extracted", "extractor_version": "test",
        "node": {"uid": uid, "kind": kind, "name": name, "statement": statement, "value": "31"},
        "evidence": list(evidence), "relations": list(relations),
    })


def test_node_detail_rule_artefact_and_missing(ontology_root, tmp_vault, client, auth_headers):
    pytest.importorskip("arcadedb_embedded")
    p = projects.create_project("work", "Orbit")
    svc = service_mod.get_service()
    svc.seed()
    svc.commit("bind", {"project": p["uuid"], "artefacts": [
        {"aid": "a1", "path": "20-contexts/work/jira/t1.md", "title": "Ticket one"}]})
    _ratify_node(svc, p["uuid"], "d1aaaaaa-1", "Decision", "grace period", "Grace is 30 days.")
    _ratify_node(svc, p["uuid"], "r1bbbbbb-2", "Rule", "lapse day", "Lapse on day 31.",
                 evidence=[{"aid": "a1", "quote": "day 31", "locator": "p1"}],
                 relations=[{"type": "DEPENDS_ON", "target_uid": "d1aaaaaa-1"}])

    d = client.get("/v1/ontology/nodes/r1bbbbbb-2", headers=auth_headers).json()
    assert d["kind"] == "rule" and d["name"] == "lapse day" and d["statement"] == "Lapse on day 31."
    assert d["value"] == "31" and d["provenance"] == "extracted" and isinstance(d["ratified_at"], str)
    assert d["note_path"] is None
    assert d["evidence"] == [{"aid": "a1", "note_path": "20-contexts/work/jira/t1.md",
                              "title": "Ticket one", "quote": "day 31", "locator": "p1"}]
    assert d["relations"] == [{"direction": "out", "type": "DEPENDS_ON", "uid": "d1aaaaaa-1",
                               "name": "grace period", "kind": "decision"}]
    assert d["generated_note_path"].endswith(".md")
    assert (tmp_vault / d["generated_note_path"]).is_file()

    other = client.get("/v1/ontology/nodes/d1aaaaaa-1", headers=auth_headers).json()
    assert other["relations"] == [{"direction": "in", "type": "DEPENDS_ON", "uid": "r1bbbbbb-2",
                                   "name": "lapse day", "kind": "rule"}]

    art = client.get("/v1/ontology/nodes/a1", headers=auth_headers).json()
    assert art["kind"] == "artefact" and art["note_path"] == "20-contexts/work/jira/t1.md"
    assert art["generated_note_path"] is None and art["evidence"] == []

    assert client.get("/v1/ontology/nodes/nope", headers=auth_headers).status_code == 404


def test_node_detail_503_when_locked(ontology_root, client, auth_headers, monkeypatch):
    monkeypatch.setattr(GoldGraph, "open", lambda self: (_ for _ in ()).throw(GraphLocked("locked by another process")))
    r = client.get("/v1/ontology/nodes/x", headers=auth_headers)
    assert r.status_code == 503 and "locked" in r.json()["detail"]


def test_enable_creates_scope_questions_and_yes_no_route(ontology_root, tmp_vault, client, auth_headers, monkeypatch):
    pytest.importorskip("arcadedb_embedded")
    from ghostbrain.ontology import onboarding, topics as topics_mod
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/a.md", "a", "Orbit kickoff. Orbit plan. Orbit team.")
    _note(tmp_vault, "20-contexts/work/b.md", "b", "Mentions Orbit once.")
    monkeypatch.setattr(onboarding.topics, "classify_notes",
                        lambda name, seeds, known, notes, run=None:
                        [topics_mod.Verdict(n.aid, "claims triage", "not_about", "r") for n in notes])
    r = client.post("/v1/ontology/projects/enable", json={"project_id": p["id"], "seeds": ["Orbit"]},
                    headers=auth_headers)
    assert r.status_code == 200
    items = client.get("/v1/ontology/backlog", params={"project": p["uuid"]}, headers=auth_headers).json()
    assert items[0]["type"] == "scope" and items[0]["scope"]["name"] == "claims triage"
    r = client.post(f"/v1/ontology/backlog/{items[0]['id']}/action", json={"action": "no"}, headers=auth_headers)
    assert r.status_code == 200
    topics = client.get(f"/v1/ontology/projects/{p['uuid']}/topics", headers=auth_headers).json()
    assert {t["name"]: t["status"] for t in topics} == {"Orbit": "in", "claims triage": "out"}


def test_rescope_returns_onboard_result_and_topics_404(ontology_root, tmp_vault, client, auth_headers, monkeypatch):
    pytest.importorskip("arcadedb_embedded")
    from ghostbrain.ontology import onboarding
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/a.md", "a", "Orbit kickoff. Orbit plan. Orbit team.")
    monkeypatch.setattr(onboarding.topics, "classify_notes", lambda *a, **k: [])
    assert client.get(f"/v1/ontology/projects/{p['uuid']}/topics", headers=auth_headers).status_code == 404
    client.post("/v1/ontology/projects/enable", json={"project_id": p["id"], "seeds": ["Orbit"]}, headers=auth_headers)
    r = client.post(f"/v1/ontology/projects/{p['uuid']}/scope", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"binding_item", "in", "unsure", "auto_in", "auto_out", "scope_items", "classified"}
    assert body["in"] == 0 and body["scope_items"] == []   # already bound by enable


def test_onboarding_already_running_is_409(ontology_root, tmp_vault, client, auth_headers, monkeypatch):
    from ghostbrain.api.routes import ontology as routes
    from ghostbrain.ontology import onboarding
    p = projects.create_project("work", "Orbit")
    monkeypatch.setattr(onboarding, "onboard", lambda svc, uuid, **kw: {
        "binding_item": None, "in": 0, "unsure": 0, "auto_in": 0, "auto_out": 0, "scope_items": [],
        "classified": 0})
    monkeypatch.setattr(service_mod.OntologyService, "seed", lambda self: 0)
    lock = routes._onboarding_lock(p["uuid"])
    assert lock.acquire(blocking=False)
    try:
        r = client.post("/v1/ontology/projects/enable", json={"project_id": p["id"], "seeds": ["Orbit"]},
                        headers=auth_headers)
        assert r.status_code == 409 and "already running" in r.json()["detail"]
        service_mod.get_service().store.enable_project(p["uuid"], ["Orbit"])
        r = client.post(f"/v1/ontology/projects/{p['uuid']}/scope", headers=auth_headers)
        assert r.status_code == 409
    finally:
        lock.release()
    r = client.post(f"/v1/ontology/projects/{p['uuid']}/scope", headers=auth_headers)
    assert r.status_code == 200


def test_topic_note_counts_follow_the_decision(ontology_root, tmp_vault, client, auth_headers):
    svc = service_mod.get_service()
    svc.store.enable_project("p1", ["Orbit"])
    for name, status, notes in (("billing", "in", {"b": "bound", "c": "excluded"}),
                                ("claims triage", "out", {"d": "excluded", "e": "scoping"}),
                                ("reporting", "pending", {"f": "scoping", "g": "bound"})):
        t = svc.store.ensure_topic("p1", name, status=status)
        for aid, state in notes.items():
            svc.store.set_note_topic("p1", aid, t["uid"])
            svc.store.upsert_binding("p1", aid, f"{aid}.md", aid, state)
    topics = client.get("/v1/ontology/projects/p1/topics", headers=auth_headers).json()
    assert {t["name"]: t["notes"] for t in topics} == {"billing": 1, "claims triage": 1, "reporting": 1}
