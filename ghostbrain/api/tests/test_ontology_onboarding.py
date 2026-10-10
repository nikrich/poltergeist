from ghostbrain.api.repo import projects
from ghostbrain.ontology import onboarding, service as service_mod, topics


def _note(vault, rel, aid, title, body):
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nid: {aid}\ntitle: {title}\n---\n{body}\n", encoding="utf-8")


def _verdicts(mapping):
    def run_classify(project_name, seeds, known, notes, *, run=None):
        return [topics.Verdict(n.aid, *mapping[n.aid]) for n in notes]
    return run_classify


def test_onboard_binds_in_and_groups_unsure_by_topic(ontology_root, tmp_vault, monkeypatch):
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/a.md", "a", "Orbit kickoff", "x")
    _note(tmp_vault, "20-contexts/work/b.md", "b", "b", "Mentions Orbit once, about claims triage.")
    _note(tmp_vault, "20-contexts/work/c.md", "c", "c", "Orbit again, claims triage backlog.")
    _note(tmp_vault, "20-contexts/personal/d.md", "d", "d", "The Orbit window repair quote.")
    monkeypatch.setattr(onboarding.topics, "classify_notes", _verdicts({
        "b": ("claims triage", "unclear", "r"), "c": ("Claims Triage", "about", "r"),
        "d": ("flat repairs", "not_about", "r")}))
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    out = onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    binding = svc.store.item(out["binding_item"])
    assert [a["aid"] for a in binding["payload"]["artefacts"]] == ["a"]
    scope_items = [svc.store.item(i) for i in out["scope_items"]]
    by_name = {s["payload"]["name"]: s["payload"] for s in scope_items}
    assert sorted(by_name) == ["claims triage", "flat repairs"]
    assert sorted(n["aid"] for n in by_name["claims triage"]["notes"]) == ["b", "c"]
    assert by_name["flat repairs"]["lean"] == "not_about"
    assert onboarding.core_topic(svc, p["uuid"])["status"] == "in"


def test_rerun_auto_routes_decided_topics_and_never_duplicates(ontology_root, tmp_vault, monkeypatch):
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/b.md", "b", "b", "Orbit once, claims triage.")
    _note(tmp_vault, "20-contexts/work/e.md", "e", "e", "Orbit once, billing.")
    monkeypatch.setattr(onboarding.topics, "classify_notes", _verdicts({
        "b": ("claims triage", "unclear", "r"), "e": ("billing", "unclear", "r"),
        "f": ("billing", "unclear", "r"), "g": ("claims triage", "about", "r")}))
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    first = onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    triage_topic = svc.store.ensure_topic(p["uuid"], "claims triage")
    svc.store.set_topic_status(triage_topic["uid"], "out")
    _note(tmp_vault, "20-contexts/work/f.md", "f", "f", "Orbit once, more billing.")
    _note(tmp_vault, "20-contexts/work/g.md", "g", "g", "Orbit once, claims triage again.")
    second = onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    assert second["auto_out"] == 1                       # g: topic already out
    billing = svc.store.ensure_topic(p["uuid"], "billing")
    item = svc.store.open_scope_item(p["uuid"], billing["uid"])
    assert sorted(n["aid"] for n in item["payload"]["notes"]) == ["e", "f"]   # appended, not duplicated
    assert len([i for i in svc.store.open_items(p["uuid"]) if i["type"] == "scope"]) == len(first["scope_items"])


def test_classifier_failure_yields_one_unclassified_item(ontology_root, tmp_vault, monkeypatch):
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/b.md", "b", "b", "Orbit once.")
    _note(tmp_vault, "20-contexts/work/c.md", "c", "c", "Orbit once too.")
    monkeypatch.setattr(onboarding.topics, "classify_notes", _verdicts({
        "b": (topics.UNCLASSIFIED, "unclear", "x"), "c": (topics.UNCLASSIFIED, "unclear", "x")}))
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    out = onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    [item] = [svc.store.item(i) for i in out["scope_items"]]
    assert item["payload"]["name"] == topics.UNCLASSIFIED and len(item["payload"]["notes"]) == 2
    assert out["binding_item"] is None


def test_unclassified_topic_is_never_auto_routed(ontology_root, tmp_vault, monkeypatch):
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/b.md", "b", "b", "Orbit once.")
    monkeypatch.setattr(onboarding.topics, "classify_notes", _verdicts({
        "b": (topics.UNCLASSIFIED, "unclear", "x")}))
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    unc = svc.store.ensure_topic(p["uuid"], topics.UNCLASSIFIED)
    svc.store.set_topic_status(unc["uid"], "out")
    out = onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    [item] = [svc.store.item(i) for i in out["scope_items"]]
    assert item["payload"]["name"] == topics.UNCLASSIFIED
    assert [n["aid"] for n in item["payload"]["notes"]] == ["b"]
    assert out["auto_out"] == 0 and out["binding_item"] is None


def test_out_topic_note_is_excluded_even_when_band_is_in(ontology_root, tmp_vault, monkeypatch):
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/a.md", "a", "Orbit kickoff", "x")
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    t = svc.store.ensure_topic(p["uuid"], "billing")
    svc.store.set_topic_status(t["uid"], "out")
    svc.store.set_note_topic(p["uuid"], "a", t["uid"])
    out = onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    assert out["auto_out"] == 1 and out["binding_item"] is None
    assert [b["status"] for b in svc.store.bindings(p["uuid"]) if b["aid"] == "a"] == ["excluded"]


def test_unsure_note_under_in_topic_is_proposed(ontology_root, tmp_vault, monkeypatch):
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/b.md", "b", "b", "Orbit once, billing.")
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    t = svc.store.ensure_topic(p["uuid"], "billing", status="in")
    svc.store.set_note_topic(p["uuid"], "b", t["uid"])
    out = onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    assert out["auto_in"] == 1
    binding = svc.store.item(out["binding_item"])
    assert [a["aid"] for a in binding["payload"]["artefacts"]] == ["b"]


def _scope_item_for(svc, out):
    [item_id] = out["scope_items"]
    return item_id


def test_unclassified_is_a_per_batch_bucket(ontology_root, tmp_vault, monkeypatch):
    import pytest
    pytest.importorskip("arcadedb_embedded")
    from ghostbrain.ontology import backlog
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/b.md", "b", "b", "Orbit once.")
    monkeypatch.setattr(onboarding.topics, "classify_notes", _verdicts({
        "b": (topics.UNCLASSIFIED, "unclear", "x"), "c": (topics.UNCLASSIFIED, "unclear", "x")}))
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    svc.seed()
    first = onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    backlog.act(svc, _scope_item_for(svc, first), "yes")                    # run 1: b is in
    _note(tmp_vault, "20-contexts/work/c.md", "c", "c", "Orbit once too.")
    second = onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    backlog.act(svc, _scope_item_for(svc, second), "no")                    # run 2: c is out
    status = {b["aid"]: b["status"] for b in svc.store.bindings(p["uuid"])}
    assert status == {"b": "bound", "c": "excluded"}
    unc = svc.store.ensure_topic(p["uuid"], topics.UNCLASSIFIED)
    assert unc["status"] == "pending"                                       # never decided

    def check(snap):
        assert {"src": "b", "type": "ABOUT", "dst": p["uuid"], "quote": None, "locator": None} in snap["edges"]
        assert not any(e["src"] == "c" and e["type"] == "ABOUT" for e in snap["edges"])
        assert not any(e["type"] in ("IN_SCOPE", "OUT_OF_SCOPE") and e["src"] == unc["uid"] for e in snap["edges"])
        assert all(n["uid"] != unc["uid"] for n in snap["nodes"])
    with svc.graph_session() as g:
        check(g.snapshot())
    svc.rebuild()
    with svc.graph_session() as g:
        check(g.snapshot())


def test_rerun_appends_to_parked_scope_item(ontology_root, tmp_vault, monkeypatch):
    from ghostbrain.ontology import backlog
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/e.md", "e", "e", "Orbit once, billing.")
    monkeypatch.setattr(onboarding.topics, "classify_notes", _verdicts({
        "e": ("billing", "unclear", "r"), "f": ("billing", "unclear", "r")}))
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    first = onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    [item] = first["scope_items"]
    backlog.act(svc, item, "investigate", note="later")
    _note(tmp_vault, "20-contexts/work/f.md", "f", "f", "Orbit once, more billing.")
    second = onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    assert second["scope_items"] == []
    assert sorted(n["aid"] for n in svc.store.item(item)["payload"]["notes"]) == ["e", "f"]


def test_short_classifier_output_is_padded_as_unclassified(ontology_root, tmp_vault, monkeypatch):
    p = projects.create_project("work", "Orbit")
    _note(tmp_vault, "20-contexts/work/b.md", "b", "b", "Orbit once.")
    _note(tmp_vault, "20-contexts/work/c.md", "c", "c", "Orbit once too.")
    monkeypatch.setattr(onboarding.topics, "classify_notes",
                        lambda name, seeds, known, notes, run=None: [topics.Verdict(notes[0].aid, "billing", "about", "r")])
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    out = onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    names = sorted(svc.store.item(i)["payload"]["name"] for i in out["scope_items"])
    assert names == ["billing", topics.UNCLASSIFIED] and out["classified"] == 2


def test_core_topic_is_in_gold_once(ontology_root, tmp_vault, monkeypatch):
    import pytest
    pytest.importorskip("arcadedb_embedded")
    p = projects.create_project("work", "Orbit")
    monkeypatch.setattr(onboarding.topics, "classify_notes", _verdicts({}))
    svc = service_mod.get_service()
    svc.store.enable_project(p["uuid"], ["Orbit"])
    svc.seed()
    onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    onboarding.onboard(svc, p["uuid"], search_fn=lambda q, l: [])
    core = onboarding.core_topic(svc, p["uuid"])
    scope_events = [e for e in svc.store.events() if e.type == "scope"]
    assert len(scope_events) == 1 and scope_events[0].actor == "system"
    assert scope_events[0].payload["topic_uid"] == core["uid"] and scope_events[0].payload["decision"] == "in"

    def check(snap):
        assert {"src": core["uid"], "type": "IN_SCOPE", "dst": p["uuid"], "quote": None,
                "locator": None} in snap["edges"]
        assert any(n["uid"] == core["uid"] and n["kind"] == "Topic" for n in snap["nodes"])
    with svc.graph_session() as g:
        check(g.snapshot())
    svc.rebuild()
    with svc.graph_session() as g:
        check(g.snapshot())
