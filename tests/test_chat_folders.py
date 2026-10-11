import json
import pytest

from ghostbrain.api.repo import chat_folders as cf, chat_store, projects


@pytest.fixture
def chats(tmp_path, monkeypatch):
    d = tmp_path / "chats"
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(d))
    return d


@pytest.fixture
def env(tmp_path, monkeypatch, chats):
    # Same minimal vault as tests/test_project_rename.py: contexts work + personal.
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    (v / "90-meta" / "routing.yaml").write_text("contexts:\n  - work\n  - personal\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(v))
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    atlas = projects.create_project("work", "Atlas")
    return {"atlas": atlas["slug"]}


def _chat(title="t"):
    c = chat_store.create()
    chat_store.append_user_message(c, title)   # non-empty so create() won't reuse it
    return c


def test_clean_path_rejects_traversal():
    for bad in ("../x", "a/../b", "/abs", ".hidden", "a/.b"):
        with pytest.raises(cf.InvalidLocation):
            cf.clean_path(bad)
    assert cf.clean_path("a//b/") == "a/b"
    assert cf.clean_path("") == ""


def test_check_location(env):
    cf.check_location("work", None)
    cf.check_location("work", env["atlas"])
    with pytest.raises(cf.InvalidLocation):
        cf.check_location("nope", None)
    with pytest.raises(cf.InvalidLocation):
        cf.check_location("work", "missing")


def test_archived_project_rejects_writes(env):
    projects.update_project("work", env["atlas"], archived=True)
    with pytest.raises(cf.InvalidLocation):
        cf.check_location("work", env["atlas"])
    cf.check_location("work", env["atlas"], for_write=False)


def test_create_and_duplicate(env):
    assert cf.create("work", None, "q4/plans") == {"context": "work", "project": None, "path": "q4/plans"}
    assert cf.folder_exists("work", None, "q4")          # implied parent
    with pytest.raises(cf.FolderExists):
        cf.create("work", None, "q4/plans")
    with pytest.raises(cf.InvalidLocation):
        cf.create("work", None, "")


def test_registry_survives_reload_and_corruption(env, chats):
    cf.create("work", None, "empty")
    assert cf.folder_exists("work", None, "empty")
    (chats / "folders.json").write_text("{not json")
    assert not cf.folder_exists("work", None, "empty")   # lost, but no crash
    c = _chat()
    cf.move_chat(c["id"], context="work", project=None, folder="kept")
    (chats / "folders.json").unlink()
    assert cf.folder_exists("work", None, "kept")        # implied by the chat


def test_move_chat_validates_and_creates_folder(env):
    c = _chat()
    out = cf.move_chat(c["id"], context="work", project=env["atlas"], folder="a/b")
    assert (out["context"], out["project"], out["folder"]) == ("work", env["atlas"], "a/b")
    assert cf.folder_exists("work", env["atlas"], "a/b")
    with pytest.raises(cf.InvalidLocation):
        cf.move_chat(c["id"], context="nope", project=None, folder=None)
    with pytest.raises(cf.ChatNotFound):
        cf.move_chat("missing", context="work", project=None, folder=None)
    out = cf.move_chat(c["id"], context=None, project=None, folder=None)
    assert out["context"] is None


def test_move_folder_rewrites_chats_and_subfolders(env):
    cf.create("work", None, "q4/empty-child")
    c = _chat()
    cf.move_chat(c["id"], context="work", project=None, folder="q4/deep")
    other = _chat()
    cf.move_chat(other["id"], context="work", project=None, folder="q40")   # prefix trap
    cf.move(("work", None, "q4"), ("work", env["atlas"], "archive/q4"))
    moved = chat_store.get(c["id"])
    assert (moved["context"], moved["project"], moved["folder"]) == ("work", env["atlas"], "archive/q4/deep")
    assert chat_store.get(other["id"])["folder"] == "q40"
    assert cf.folder_exists("work", env["atlas"], "archive/q4/empty-child")
    assert not cf.folder_exists("work", None, "q4")


def test_move_folder_rejections_leave_chats_alone(env):
    cf.create("work", None, "a")
    cf.create("work", None, "b")
    c = _chat()
    cf.move_chat(c["id"], context="work", project=None, folder="a")
    with pytest.raises(cf.InvalidLocation):
        cf.move(("work", None, "a"), ("work", None, "a/inner"))
    with pytest.raises(cf.FolderExists):
        cf.move(("work", None, "a"), ("work", None, "b"))
    with pytest.raises(cf.FolderNotFound):
        cf.move(("work", None, "zzz"), ("work", None, "y"))
    projects.update_project("work", env["atlas"], archived=True)
    with pytest.raises(cf.InvalidLocation):
        cf.move(("work", None, "a"), ("work", env["atlas"], "a"))
    assert chat_store.get(c["id"])["folder"] == "a"


def test_delete_only_empty(env):
    cf.create("work", None, "x/y")
    with pytest.raises(cf.FolderNotEmpty):
        cf.delete("work", None, "x")
    cf.delete("work", None, "x/y")
    cf.delete("work", None, "x")
    assert not cf.folder_exists("work", None, "x")
    c = _chat()
    cf.move_chat(c["id"], context="work", project=None, folder="busy")
    with pytest.raises(cf.FolderNotEmpty):
        cf.delete("work", None, "busy")
    with pytest.raises(cf.FolderNotFound):
        cf.delete("work", None, "never")


def test_tree_shape(env):
    cf.create("work", env["atlas"], "plans")
    c = _chat("in plans")
    cf.move_chat(c["id"], context="work", project=env["atlas"], folder="plans")
    loose = _chat("loose")
    t = cf.tree()
    assert [x["id"] for x in t["unfiled"]] == [loose["id"]]
    scopes = {(s["context"], s["project"]): s for s in t["scopes"]}
    assert ("work", None) in scopes and ("personal", None) in scopes
    atlas = scopes[("work", env["atlas"])]
    assert atlas["name"] == "Atlas" and atlas["archived"] is False
    [plans] = atlas["folders"]
    assert plans["name"] == "plans" and plans["path"] == "plans"
    assert [x["id"] for x in plans["chats"]] == [c["id"]]


def test_tree_orphaned_chat_lands_in_unfiled(env, chats):
    raw = {"id": "orph", "title": "o", "created_at": 1, "updated_at": 1, "messages": [],
           "context": "gone", "project": None, "folder": None, "auto_filed": "done"}
    chats.mkdir(parents=True, exist_ok=True)
    (chats / "orph.json").write_text(json.dumps(raw))
    ghost = _chat()
    chat_store.move(ghost["id"], context="work", project="deleted-proj", folder=None)
    t = cf.tree()
    flagged = {x["id"]: x["unknown_location"] for x in t["unfiled"]}
    assert flagged == {"orph": True, ghost["id"]: True}


def test_tree_hides_empty_archived_projects(env):
    empty = projects.create_project("work", "Old")
    projects.update_project("work", empty["slug"], archived=True)
    keys = {(s["context"], s["project"]) for s in cf.tree()["scopes"]}
    assert ("work", empty["slug"]) not in keys


def test_repoint_project(env):
    cf.create("work", env["atlas"], "plans")
    c = _chat()
    cf.move_chat(c["id"], context="work", project=env["atlas"], folder="plans")
    cf.repoint_project("work", env["atlas"], "atlas-2")
    assert chat_store.get(c["id"])["project"] == "atlas-2"
    assert ("work", "atlas-2", "plans") in cf._registry()   # registry entry moved too
