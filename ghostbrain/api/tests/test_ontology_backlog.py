import pytest

from ghostbrain.ontology import backlog, service as service_mod
from ghostbrain.ontology.extract import CandidateIn
from ghostbrain.ontology import triage


class FakeEmbedder:
    def encode(self, texts):
        return [[float(len(t)), 1.0] for t in texts]


def _candidate(svc, project="p1"):
    c = CandidateIn(kind="Rule", name="lapse day", statement="Today lapse is day 31.", value="31",
                    existing_uid=None, quote="day 31", locator="", confidence=0.7)
    svc.store.upsert_binding(project, "a1", "20-contexts/work/a1.md", "A1", "bound")
    _, cid = triage.triage(svc.store, project, "a1", c, FakeEmbedder())
    return cid, svc.store.open_items(project)[-1]["id"]


def test_ratify_candidate_with_edit_commits_full_payload(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    cid, item = _candidate(svc)
    seq = backlog.act(svc, item, "ratify", value="30")
    ev = svc.store.events()[-1]
    assert ev.seq == seq and ev.type == "ratify"
    assert ev.payload["node"]["value"] == "30" and ev.payload["candidate_id"] == cid
    assert ev.payload["evidence"][0]["aid"] == "a1" and ev.payload["provenance"] == "extracted"
    assert len(ev.payload["node"]["uid"]) == 32
    assert svc.store.candidate(cid)["status"] == "ratified"


def test_double_ratify_conflicts_and_logs_once(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    _, item = _candidate(svc)
    backlog.act(svc, item, "ratify")
    with pytest.raises(backlog.ItemClosed):
        backlog.act(svc, item, "ratify")
    assert [e.type for e in svc.store.events()].count("ratify") == 1


def test_reject_and_investigate(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    cid, item = _candidate(svc)
    backlog.act(svc, item, "reject")
    assert svc.store.candidate(cid)["status"] == "rejected"
    assert svc.store.events()[-1].type == "reject"
    cid2, item2 = _candidate(svc, project="p2")
    backlog.act(svc, item2, "investigate", note="check with PO")
    assert svc.store.item(item2)["status"] == "parked"
    assert svc.store.candidate(cid2)["status"] == "investigating"


def test_binding_ratify_with_exclusions(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    item = svc.store.add_item("p1", "binding", payload={"artefacts": [
        {"aid": "a1", "path": "x.md", "title": "X"}, {"aid": "a2", "path": "y.md", "title": "Y"}]})
    backlog.act(svc, item, "ratify", exclude=["a2"])
    ev = svc.store.events()[-1]
    assert ev.type == "bind" and [a["aid"] for a in ev.payload["artefacts"]] == ["a1"]
    assert {b["aid"]: b["status"] for b in svc.store.bindings("p1")} == {"a1": "bound", "a2": "excluded"}


def test_list_items_shapes(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    _candidate(svc)
    svc.store.add_item("p1", "binding", payload={"artefacts": [{"aid": "a9", "path": "z.md", "title": "Z"}]})
    items = backlog.list_items(svc, "p1")
    assert items[0]["type"] == "binding" and items[0]["artefacts"][0]["aid"] == "a9"
    cand = items[1]["candidate"]
    assert cand["evidence"][0] == {"aid": "a1", "path": "20-contexts/work/a1.md", "title": "A1",
                                   "quote": "day 31", "locator": ""}


def test_unknown_action_and_missing_item(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    _, item = _candidate(svc)
    with pytest.raises(backlog.BadAction):
        backlog.act(svc, item, "pick_a")
    with pytest.raises(backlog.ItemNotFound):
        backlog.act(svc, 9999, "ratify")


def test_failed_append_reopens_item_and_retry_succeeds(ontology_root, tmp_vault, monkeypatch):
    svc = service_mod.get_service()
    cid, item = _candidate(svc)
    real_append = svc.store.append_event
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real_append(*args, **kwargs)

    monkeypatch.setattr(svc.store, "append_event", flaky)
    with pytest.raises(OSError):
        backlog.act(svc, item, "ratify")
    assert svc.store.item(item)["status"] == "open"
    assert svc.store.candidate(cid)["status"] == "pending"
    seq = backlog.act(svc, item, "ratify")
    assert [e.type for e in svc.store.events()].count("ratify") == 1
    assert svc.store.events()[-1].seq == seq
    assert svc.store.item(item)["status"] == "resolved"


def test_binding_ratify_records_exclusions(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    item = svc.store.add_item("p1", "binding", payload={"artefacts": [
        {"aid": "a1", "path": "x.md", "title": "X"}, {"aid": "a2", "path": "y.md", "title": "Y"}]})
    seq = backlog.act(svc, item, "ratify", exclude=["a2"])
    ev = svc.store.events()[-1]
    assert ev.seq == seq and ev.type == "bind"
    assert ev.payload["excluded"] == ["a2"]


def test_binding_reject_logs_all_excluded(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    item = svc.store.add_item("p1", "binding", payload={"artefacts": [
        {"aid": "a1", "path": "x.md", "title": "X"}, {"aid": "a2", "path": "y.md", "title": "Y"}]})
    seq = backlog.act(svc, item, "reject")
    ev = svc.store.events()[-1]
    assert ev.seq == seq and ev.type == "bind"
    assert ev.payload["artefacts"] == [] and ev.payload["excluded"] == ["a1", "a2"]
    assert svc.store.item(item)["status"] == "resolved"


def test_binding_investigate_logs_event(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    item = svc.store.add_item("p1", "binding", payload={"artefacts": [
        {"aid": "a1", "path": "x.md", "title": "X"}]})
    seq = backlog.act(svc, item, "investigate", note="check later")
    ev = svc.store.events()[-1]
    assert ev.seq == seq and ev.type == "investigate"
    assert ev.payload == {"item_id": item, "note": "check later"}
    assert svc.store.item(item)["status"] == "parked"
    assert {b["aid"]: b["status"] for b in svc.store.bindings("p1")} == {"a1": "proposed"}


def test_missing_candidate_raises_and_item_stays_open(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    _, item = _candidate(svc)
    svc.store._db.execute("DELETE FROM candidates")
    with pytest.raises(backlog.ItemNotFound):
        backlog.act(svc, item, "ratify")
    assert svc.store.item(item)["status"] == "open"


def _scope_item(svc, project, topic_name, aids):
    t = svc.store.ensure_topic(project, topic_name)
    for a in aids:
        svc.store.set_note_topic(project, a, t["uid"])
        svc.store.upsert_binding(project, a, f"20-contexts/work/{a}.md", a.upper(), "scoping")
    item = svc.store.add_item(project, "scope", payload={
        "topic_uid": t["uid"], "name": topic_name, "lean": "unclear",
        "notes": [{"aid": a, "path": f"20-contexts/work/{a}.md", "title": a.upper(), "reason": "r"} for a in aids]})
    return t, item


def test_scope_yes_binds_and_releases_waiting(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    t, item = _scope_item(svc, "p1", "claims triage", ["a1", "a2"])
    cid = svc.store.add_candidate("p1", kind="Rule", name="n", statement="s", value=None, existing_uid=None,
                                  relations=[], confidence=0.6, extractor_version="v", embedding=None,
                                  topic_uid=t["uid"], status="waiting_scope")
    backlog.act(svc, item, "yes", exclude=["a2"])
    ev = svc.store.events()[-1]
    assert ev.type == "scope" and ev.payload["decision"] == "in"
    assert [a["aid"] for a in ev.payload["artefacts"]] == ["a1"] and ev.payload["excluded"] == ["a2"]
    assert svc.store.topic(t["uid"])["status"] == "in"
    assert {b["aid"]: b["status"] for b in svc.store.bindings("p1")} == {"a1": "bound", "a2": "excluded"}
    assert svc.store.candidate(cid)["status"] == "pending"
    assert any(i["candidate_id"] == cid for i in svc.store.open_items("p1"))


def test_scope_no_excludes_everything_in_topic_and_rejects_waiting(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    t, item = _scope_item(svc, "p1", "claims triage", ["a1"])
    svc.store.set_note_topic("p1", "a9", t["uid"])                      # bound earlier, same topic
    svc.store.upsert_binding("p1", "a9", "20-contexts/work/a9.md", "A9", "bound")
    cid = svc.store.add_candidate("p1", kind="Rule", name="n", statement="s", value=None, existing_uid=None,
                                  relations=[], confidence=0.6, extractor_version="v", embedding=None,
                                  topic_uid=t["uid"], status="waiting_scope")
    backlog.act(svc, item, "reject")                                    # synonym for no
    ev = svc.store.events()[-1]
    assert ev.payload["decision"] == "out" and sorted(ev.payload["excluded"]) == ["a1", "a9"]
    assert svc.store.topic(t["uid"])["status"] == "out"
    assert {b["status"] for b in svc.store.bindings("p1")} == {"excluded"}
    assert svc.store.candidate(cid)["status"] == "rejected"


def test_scope_double_answer_conflicts_once_in_log(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    _, item = _scope_item(svc, "p1", "billing", ["a1"])
    backlog.act(svc, item, "no")
    with pytest.raises(backlog.ItemClosed):
        backlog.act(svc, item, "yes")
    assert [e.type for e in svc.store.events()].count("scope") == 1


def test_scope_items_listed_first_and_yes_rejected_on_candidates(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    cid, cand_item = _candidate(svc)
    _, item = _scope_item(svc, "p1", "billing", ["a3"])
    items = backlog.list_items(svc, "p1")
    assert items[0]["type"] == "scope" and items[0]["scope"]["name"] == "billing"
    with pytest.raises(backlog.BadAction):
        backlog.act(svc, cand_item, "yes")


def test_scope_yes_never_excludes_extraction_raised_notes(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    t = svc.store.ensure_topic("p1", "billing")
    svc.store.upsert_binding("p1", "a1", "20-contexts/work/a1.md", "A1", "bound")
    item = svc.store.add_item("p1", "scope", payload={
        "topic_uid": t["uid"], "name": "billing", "lean": "unclear",
        "notes": [{"aid": "a1", "path": "20-contexts/work/a1.md", "title": "A1",
                   "reason": "raised by extraction", "raised_by": "extraction"}]})
    backlog.act(svc, item, "yes", exclude=["a1"])                        # unticking it is a no-op
    ev = svc.store.events()[-1]
    assert ev.payload["artefacts"] == [] and ev.payload["excluded"] == []
    assert {b["aid"]: b["status"] for b in svc.store.bindings("p1")} == {"a1": "bound"}


def _waiting(svc, project, topic_uid, aid, statement, value="31"):
    c = CandidateIn(kind="Rule", name="lapse day", statement=statement, value=value,
                    existing_uid=None, quote=statement, locator="", confidence=0.6)
    _, cid = triage.triage(svc.store, project, aid, c, FakeEmbedder(), topic_uid=topic_uid, status="waiting_scope")
    return cid


def test_scope_yes_releases_waiting_through_dedup(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    t, item = _scope_item(svc, "p1", "billing", ["a1"])
    first = _waiting(svc, "p1", t["uid"], "a1", "Lapse is day 31.")
    second = _waiting(svc, "p1", t["uid"], "a2", "Lapse is day 31.")        # same fact, other note
    backlog.act(svc, item, "yes")
    cands = [i for i in svc.store.open_items("p1") if i["type"] == "candidate"]
    assert [i["candidate_id"] for i in cands] == [first]
    assert {e["aid"] for e in svc.store.evidence(first)} == {"a1", "a2"}
    assert svc.store.candidate(second)["status"] == "merged"


def test_scope_yes_drops_waiting_near_a_rejected_fact(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    t, item = _scope_item(svc, "p1", "billing", ["a1"])
    rejected = _waiting(svc, "p1", t["uid"], "a9", "Lapse is day 31.")
    svc.store.set_candidate_status(rejected, "rejected")
    held = _waiting(svc, "p1", t["uid"], "a1", "Lapse is day 31.")
    backlog.act(svc, item, "yes")
    assert not [i for i in svc.store.open_items("p1") if i["type"] == "candidate"]
    assert svc.store.candidate(held)["status"] == "dropped"


def test_scope_answer_on_topic_decided_elsewhere_conflicts(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    t, item = _scope_item(svc, "p1", "billing", ["a1"])
    svc.store.set_topic_status(t["uid"], "out")
    with pytest.raises(backlog.ItemClosed):
        backlog.act(svc, item, "yes")
    assert [e.type for e in svc.store.events()].count("scope") == 0


def test_scope_decision_closes_other_items_for_the_topic(ontology_root, tmp_vault):
    svc = service_mod.get_service()
    t, first = _scope_item(svc, "p1", "billing", ["a1"])
    _, parked = _scope_item(svc, "p1", "billing", ["a2"])
    backlog.act(svc, parked, "investigate", note="later")
    _, other = _scope_item(svc, "p1", "billing", ["a3"])
    backlog.act(svc, first, "no")
    assert {svc.store.item(i)["status"] for i in (parked, other)} == {"resolved"}
    assert sorted(svc.store.events()[-1].payload["excluded"]) == ["a1", "a2", "a3"]
    assert {b["status"] for b in svc.store.bindings("p1")} == {"excluded"}
    with pytest.raises(backlog.ItemClosed):
        backlog.act(svc, other, "yes")
