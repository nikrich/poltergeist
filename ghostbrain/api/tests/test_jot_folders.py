from datetime import UTC, datetime, timedelta

import frontmatter
import pytest

from ghostbrain.api.repo import jot_folders as jf
from ghostbrain.api.repo import notes_manual as nm
from ghostbrain.api.repo import projects

T0 = datetime(2026, 5, 14, 9, tzinfo=UTC)


@pytest.fixture
def env(tmp_vault, tmp_state_dir):
    (tmp_vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    return {"vault": tmp_vault, "atlas": projects.create_project("work", "Atlas")["slug"]}


def _jot(text="hello", minutes=0):
    return nm.write_inbox_jot(text, captured_at=T0 + timedelta(minutes=minutes))["id"]


def _fm(env, jid):
    return frontmatter.load(env["vault"] / nm.read_jot(jid)["path"])


def _scope(t, ctx, proj=None):
    return next(s for s in t["scopes"] if (s["context"], s["project"]) == (ctx, proj))


def test_create_and_delete_empty_folder(env):
    assert jf.create("work", env["atlas"], "q4/plans") == {"context": "work", "project": env["atlas"], "path": "q4/plans"}
    with pytest.raises(jf.sf.FolderExists):
        jf.create("work", env["atlas"], "q4/plans")
    assert ("work", env["atlas"], "q4") in jf._all_folders()
    with pytest.raises(jf.sf.FolderNotEmpty):
        jf.delete("work", env["atlas"], "q4")
    jf.delete("work", env["atlas"], "q4/plans")
    jf.delete("work", env["atlas"], "q4")
    assert jf._all_folders() == set()


def test_create_rejects_bad_location_and_path(env):
    with pytest.raises(jf.sf.InvalidLocation):
        jf.create("nope", None, "x")
    with pytest.raises(jf.sf.InvalidLocation):
        jf.create("work", None, "../x")
    projects.update_project("work", env["atlas"], archived=True)
    with pytest.raises(jf.sf.InvalidLocation):
        jf.create("work", env["atlas"], "x")


def test_delete_refuses_folder_holding_a_jot(env):
    jid = _jot()
    jf.move_jot_to(jid, context="work", project=None, folder="ideas")
    with pytest.raises(jf.sf.FolderNotEmpty):
        jf.delete("work", None, "ideas")


def test_move_jot_into_new_folder_registers_it(env):
    jid = _jot()
    jf.move_jot_to(jid, context="work", project=env["atlas"], folder="a/b")
    fm = _fm(env, jid)
    assert (fm["context"], fm["project"], fm["folder"]) == ("work", env["atlas"], "a/b")
    assert ("work", env["atlas"], "a/b") in jf._registry()


def test_move_pending_jot_into_folder_files_it(env):
    jid = _jot()
    jf.move_jot_to(jid, context="work", project=None, folder="ideas")
    fm = _fm(env, jid)
    assert fm["routingStatus"] == "routed"
    assert "00-inbox" not in nm.read_jot(jid)["path"]
    t = jf.tree()
    assert t["inbox"] == []
    assert _scope(t, "work")["folders"][0]["jots"][0]["id"] == jid


def test_move_jot_errors(env):
    with pytest.raises(jf.JotMissing):
        jf.move_jot_to("manual-19000101T000000-nope", context="work", project=None, folder=None)
    jid = _jot()
    with pytest.raises(jf.sf.InvalidLocation):
        jf.move_jot_to(jid, context="work", project=None, folder="../x")


def test_tree_sections_and_order(env):
    pending = _jot("pending one", 0)
    review = _jot("review one", 1)
    nm.mark_manual_review(review, reasoning="unsure")
    old = _jot("old", 2)
    new = _jot("new", 3)
    jf.move_jot_to(old, context="work", project=None, folder=None)
    jf.move_jot_to(new, context="work", project=None, folder=None)
    t = jf.tree()
    assert [j["id"] for j in t["inbox"]] == [pending]
    assert [j["id"] for j in t["unrouted"]] == [review]
    assert [j["id"] for j in _scope(t, "work")["jots"]] == [new, old]
    assert _scope(t, "work")["jots"][0]["unknownLocation"] is False


def test_unknown_context_goes_to_unrouted(env):
    jid = _jot()
    jf.move_jot_to(jid, context="personal", project=None, folder=None)
    (env["vault"] / "90-meta" / "routing.yaml").write_text("contexts:\n  - work\n", encoding="utf-8")
    t = jf.tree()
    assert [(j["id"], j["unknownLocation"]) for j in t["unrouted"]] == [(jid, True)]


def test_invalid_folder_field_shows_at_root(env):
    jid = _jot()
    jf.move_jot_to(jid, context="work", project=None, folder=None)
    nm.set_frontmatter_fields(jid, {"folder": "../escape"})
    t = jf.tree()
    work = _scope(t, "work")
    assert [j["id"] for j in work["jots"]] == [jid]
    assert work["folders"] == []


def test_failed_move_does_not_register_folder(env):
    with pytest.raises(jf.JotMissing):
        jf.move_jot_to("manual-19000101T000000-nope", context="work", project=None, folder="ghost")
    assert ("work", None, "ghost") not in jf._all_folders()


def test_rename_folder_same_location(env):
    jid = _jot()
    jf.move_jot_to(jid, context="work", project=None, folder="q4/plans")
    jf.create("work", None, "q4/empty")
    path_before = nm.read_jot(jid)["path"]
    assert jf.move_folder(("work", None, "q4"), ("work", None, "2026q4")) == {"context": "work", "project": None, "path": "2026q4"}
    assert _fm(env, jid)["folder"] == "2026q4/plans"
    assert nm.read_jot(jid)["path"] == path_before
    assert ("work", None, "2026q4/empty") in jf._registry()
    assert not any(p.startswith("q4") for c, _, p in jf._all_folders())


def test_move_folder_across_locations_moves_files(env):
    a, b = _jot("a"), _jot("b", 1)
    jf.move_jot_to(a, context="work", project=None, folder="q4")
    jf.move_jot_to(b, context="work", project=None, folder="q4/deep")
    jf.move_folder(("work", None, "q4"), ("work", env["atlas"], "q4"))
    for jid, folder in ((a, "q4"), (b, "q4/deep")):
        fm = _fm(env, jid)
        assert (fm["context"], fm["project"], fm["folder"]) == ("work", env["atlas"], folder)
        assert f"projects/{env['atlas']}/" in nm.read_jot(jid)["path"]


def test_move_folder_errors(env):
    jf.create("work", None, "a/b")
    jf.create("work", None, "c")
    with pytest.raises(jf.sf.FolderNotFound):
        jf.move_folder(("work", None, "zzz"), ("work", None, "y"))
    with pytest.raises(jf.sf.InvalidLocation):
        jf.move_folder(("work", None, "a"), ("work", None, "a/b/x"))
    with pytest.raises(jf.sf.FolderExists):
        jf.move_folder(("work", None, "a"), ("work", None, "c"))
    projects.update_project("work", env["atlas"], archived=True)
    with pytest.raises(jf.sf.InvalidLocation):
        jf.move_folder(("work", None, "a"), ("work", env["atlas"], "a"))


def test_move_folder_partial_failure_reports_ids(env, monkeypatch):
    good, bad = _jot("good"), _jot("bad", 1)
    jf.move_jot_to(good, context="work", project=None, folder="q4")
    jf.move_jot_to(bad, context="work", project=None, folder="q4")
    real = nm.move_jot

    def flaky(jot_id, **kw):
        if jot_id == bad:
            raise nm.JotNotFound(jot_id)
        return real(jot_id, **kw)

    monkeypatch.setattr(nm, "move_jot", flaky)
    with pytest.raises(jf.FolderMoveIncomplete) as ei:
        jf.move_folder(("work", None, "q4"), ("work", env["atlas"], "q4"))
    assert bad in str(ei.value)
    assert _fm(env, good)["project"] == env["atlas"]
    t = jf.tree()
    old = next(f for f in _scope(t, "work")["folders"] if f["path"] == "q4")
    assert [j["id"] for j in old["jots"]] == [bad]


@pytest.mark.parametrize("bad", ["2024", "[a, b]"])
def test_non_string_folder_field_shows_at_root(env, bad):
    jid = _jot()
    jf.move_jot_to(jid, context="work", project=None, folder=None)
    path = env["vault"] / nm.read_jot(jid)["path"]
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("\n---\n", f"\nfolder: {bad}\n---\n", 1), encoding="utf-8")
    assert nm.list_jots()["items"][0]["folder"] is None
    work = _scope(jf.tree(), "work")
    assert [j["id"] for j in work["jots"]] == [jid]
    assert work["folders"] == []


def test_row_with_non_string_folder_is_root():
    assert jf._folder_of({"folder": 2024}) == ""
    assert jf._folder_of({"folder": ["a"]}) == ""


def test_routing_does_not_overwrite_a_user_filing(env, monkeypatch):
    from ghostbrain.worker.router import RoutingDecision

    jid = _jot()

    def slow_router(event, **kw):
        jf.move_jot_to(jid, context="personal", project=None, folder="mine")
        return RoutingDecision(context="work", confidence=0.9, reasoning="r", method="llm", secondary_contexts=[])

    monkeypatch.setattr(nm, "route_event", slow_router)
    nm.route_existing_jot(jid)
    fm = _fm(env, jid)
    assert fm["context"] == "personal" and fm["folder"] == "mine" and fm["routingMethod"] == "user"


def test_routing_review_mark_does_not_overwrite_a_user_filing(env, monkeypatch):
    from ghostbrain.worker.router import RoutingDecision

    jid = _jot()

    def slow_router(event, **kw):
        jf.move_jot_to(jid, context="personal", project=None, folder="mine")
        return RoutingDecision(context="needs_review", confidence=0.1, reasoning="r", method="llm",
                               secondary_contexts=[])

    monkeypatch.setattr(nm, "route_event", slow_router)
    nm.route_existing_jot(jid)
    fm = _fm(env, jid)
    assert fm["routingStatus"] == "routed" and fm["folder"] == "mine"


def test_move_jot_conflict_maps_to_409(env, monkeypatch):
    from ghostbrain.vault_write import WriteConflict

    jid = _jot()

    def boom(*a, **kw):
        raise WriteConflict("stale")

    monkeypatch.setattr(nm, "move_jot", boom)
    with pytest.raises(jf.JotConflict) as ei:
        jf.move_jot_to(jid, context="work", project=None, folder=None)
    assert ei.value.status == 409
