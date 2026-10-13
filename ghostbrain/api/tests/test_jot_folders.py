from datetime import datetime, timedelta, timezone

import frontmatter
import pytest

from ghostbrain.api.repo import jot_folders as jf, notes_manual as nm, projects


T0 = datetime(2026, 5, 14, 9, tzinfo=timezone.utc)


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
