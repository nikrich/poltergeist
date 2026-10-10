import sqlite3

import pytest

from ghostbrain.ontology.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "ontology.db")
    yield s
    s.close()


def test_log_appends_monotonic_and_reads_back(store):
    a = store.append_event("seed", {"nodes": []})
    b = store.append_event("bind", {"project": "p"}, actor="system")
    assert b == a + 1
    evs = store.events()
    assert [(e.seq, e.type, e.actor) for e in evs] == [(a, "seed", "user"), (b, "bind", "system")]
    assert evs[1].payload == {"project": "p"}
    assert [e.seq for e in store.events(after=a)] == [b]
    assert store.head() == b


def test_log_is_append_only(store):
    store.append_event("seed", {})
    with pytest.raises(sqlite3.DatabaseError):
        store._db.execute("UPDATE log SET type = 'x'")
    with pytest.raises(sqlite3.DatabaseError):
        store._db.execute("DELETE FROM log")


def test_unknown_event_type_rejected(store):
    with pytest.raises(ValueError):
        store.append_event("nope", {})


def test_identity_is_stable_and_relabels(store):
    u = store.ensure_identity("context", "work", "work")
    assert store.ensure_identity("context", "work", "work") == u
    store.relabel_identity(u, "job", "job")
    assert store.identity_by_key("context", "job")["uuid"] == u
    assert store.identity_by_key("context", "work") is None


def test_candidates_evidence_and_items(store):
    cid = store.add_candidate(
        "p1", kind="Rule", name="lapse day", statement="Policies lapse on day 31.",
        value="31", existing_uid=None, relations=[{"type": "DEFINES", "target_uid": "x"}],
        confidence=0.7, extractor_version="v1", embedding=b"\x00\x00\x80?",
    )
    store.add_evidence(cid, "a1", "lapse on day 31", "## Rules")
    c = store.candidate(cid)
    assert c["status"] == "pending" and c["relations"][0]["type"] == "DEFINES"
    assert store.evidence(cid) == [{"aid": "a1", "quote": "lapse on day 31", "locator": "## Rules"}]
    item = store.add_item("p1", "candidate", candidate_id=cid)
    assert [i["id"] for i in store.open_items("p1")] == [item]
    assert store.resolve_item(item, "ratified") is True
    assert store.resolve_item(item, "ratified") is False  # double-ratify guard
    assert store.open_items("p1") == []


def test_extraction_idempotency_key(store):
    assert not store.extraction_done("p", "a", "h", "v1")
    store.record_extraction("p", "a", "h", "v1", "ok")
    assert store.extraction_done("p", "a", "h", "v1")
    assert not store.extraction_done("p", "a", "h", "v2")


def test_bindings_and_enabled_projects(store):
    store.enable_project("p1", ["Orbit", "lapse"])
    assert store.project_seeds("p1") == ["Orbit", "lapse"]
    store.upsert_binding("p1", "a1", "20-contexts/work/x.md", "X", "proposed")
    store.upsert_binding("p1", "a1", "20-contexts/work/x.md", "X", "bound")
    assert [b["status"] for b in store.bindings("p1")] == ["bound"]
    assert store.bindings("p1", "excluded") == []


def test_concurrent_reads_and_writes_are_safe(store):
    import threading

    threads_n, ops = 4, 200
    errors: list[Exception] = []

    def worker(n: int) -> None:
        try:
            for i in range(ops):
                store.append_event("seed", {"t": n, "i": i})
                store.head()
                store.events(after=0)
                store.upsert_binding(f"p{n}", f"a{i % 10}", "x.md", "t", "bound")
                store.bindings(f"p{n}")
                store.extraction_done(f"p{n}", "a", "h", "v")
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=worker, args=(n,)) for n in range(threads_n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    assert store.head() == threads_n * ops
    assert len(store.events()) == threads_n * ops
    assert all(len(store.bindings(f"p{n}")) == 10 for n in range(threads_n))


def test_topics_are_normalised_and_status_sticky(tmp_path):
    from ghostbrain.ontology.store import Store, norm_topic
    s = Store(tmp_path / "o.db")
    t = s.ensure_topic("p1", "Claims  Triage")
    assert t["status"] == "pending" and t["norm"] == norm_topic("claims triage") == "claims triage"
    s.set_topic_status(t["uid"], "out")
    again = s.ensure_topic("p1", "claims triage", status="in")
    assert again["uid"] == t["uid"] and again["status"] == "out"
    core = s.ensure_topic("p1", "Orbit", status="in")
    assert [x["name"] for x in s.topics("p1")] == ["Orbit", "Claims  Triage"]
    assert core["status"] == "in"
    s.close()


def test_note_topics_and_topic_candidates(tmp_path):
    from ghostbrain.ontology.store import Store
    s = Store(tmp_path / "o.db")
    t = s.ensure_topic("p1", "billing")
    s.set_note_topic("p1", "a1", t["uid"])
    s.set_note_topic("p1", "a2", t["uid"])
    assert s.note_topic("p1", "a1") == t["uid"] and s.notes_for_topic("p1", t["uid"]) == ["a1", "a2"]
    cid = s.add_candidate("p1", kind="Rule", name="n", statement="s", value=None, existing_uid=None,
                          relations=[], confidence=0.5, extractor_version="v", embedding=None,
                          topic_uid=t["uid"], status="waiting_scope")
    assert [c["id"] for c in s.candidates_for_topic("p1", t["uid"], "waiting_scope")] == [cid]
    assert s.candidates("p1", "pending") == []
    s.close()


def test_open_scope_item_lookup_and_payload_update(tmp_path):
    from ghostbrain.ontology.store import Store
    s = Store(tmp_path / "o.db")
    item = s.add_item("p1", "scope", payload={"topic_uid": "t1", "name": "billing", "notes": []})
    assert s.open_scope_item("p1", "t1")["id"] == item
    s.update_item_payload(item, {"topic_uid": "t1", "name": "billing", "notes": [{"aid": "a1"}]})
    assert s.item(item)["payload"]["notes"] == [{"aid": "a1"}]
    s.resolve_item(item, "yes")
    assert s.open_scope_item("p1", "t1") is None
    s.close()


def test_store_migrates_existing_db_without_topic_column(tmp_path):
    import sqlite3
    from ghostbrain.ontology.store import Store
    path = tmp_path / "o.db"
    Store(path).close()
    db = sqlite3.connect(path)
    cols = [r[1] for r in db.execute("PRAGMA table_info(candidates)")]
    db.close()
    assert "topic_uid" in cols
    Store(path).close()   # reopening an already-migrated db must not fail
