
import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo import scoped_folders as sf


@pytest.fixture
def env(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    (v / "90-meta" / "routing.yaml").write_text("contexts:\n  - work\n  - personal\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(v))
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


def test_registry_round_trip_and_corrupt(tmp_path):
    reg = sf.Registry(lambda: tmp_path / "r" / "f.json", "test")
    assert reg.load() == set()
    reg.save({("work", None, "a"), ("work", "atlas", "b/c")})
    assert reg.load() == {("work", None, "a"), ("work", "atlas", "b/c")}
    (tmp_path / "r" / "f.json").write_text("{not json", encoding="utf-8")
    assert reg.load() == set()


def test_registry_repoint(tmp_path):
    reg = sf.Registry(lambda: tmp_path / "f.json", "test")
    reg.save({("work", "old", "a"), ("work", None, "b"), ("personal", "old", "c")})
    reg.repoint("work", "old", "new")
    assert reg.load() == {("work", "new", "a"), ("work", None, "b"), ("personal", "old", "c")}


def test_with_parents_and_under():
    assert sf.with_parents({("w", None, "a/b/c")}) == {("w", None, "a"), ("w", None, "a/b"), ("w", None, "a/b/c")}
    assert sf.under("a/b", "a") and sf.under("a", "a") and not sf.under("ab", "a")


def test_build_scopes_shapes_and_sorts(env):
    atlas = projects.create_project("work", "Atlas")["slug"]
    folders = {("work", None, "q4"), ("work", None, "q4/plans")}
    by_loc = {
        ("work", None): {"": [{"id": "x", "t": 1}, {"id": "y", "t": 3}], "q4/plans": [{"id": "z", "t": 2}]},
    }
    scopes = sf.build_scopes(folders, by_loc, leaf_key="jots", sort_key="t")
    assert [(s["context"], s["project"]) for s in scopes] == [("work", None), ("work", atlas), ("personal", None)]
    work = scopes[0]
    assert [j["id"] for j in work["jots"]] == ["y", "x"]
    assert work["folders"][0]["name"] == "q4"
    assert work["folders"][0]["folders"][0]["jots"][0]["id"] == "z"


def test_build_scopes_hides_empty_archived_project(env):
    slug = projects.create_project("work", "Old")["slug"]
    projects.update_project("work", slug, archived=True)
    scopes = sf.build_scopes(set(), {}, leaf_key="jots", sort_key="t")
    assert ("work", slug) not in [(s["context"], s["project"]) for s in scopes]
