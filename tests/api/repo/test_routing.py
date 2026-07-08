import pytest
import yaml
from ghostbrain.api.repo.routing import load_routing, merge_routing, remove_routing_path


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"; (v / "90-meta").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(v))
    return v


def test_load_empty_when_missing(vault):
    assert load_routing() == {}


def test_merge_creates_and_preserves(vault):
    merge_routing({"joplin": {"token": "abc"}})
    merge_routing({"github": {"orgs": {"Acme": "work"}}})
    doc = load_routing()
    assert doc["joplin"]["token"] == "abc"
    assert doc["github"]["orgs"]["Acme"] == "work"


def test_deep_merge_does_not_clobber_sibling(vault):
    merge_routing({"gmail": {"accounts": {"a@x.com": {}}}})
    merge_routing({"gmail": {"accounts": {"b@x.com": {}}}})
    assert set(load_routing()["gmail"]["accounts"]) == {"a@x.com", "b@x.com"}


def test_remove_path(vault):
    merge_routing({"joplin": {"token": "abc", "host": "h"}})
    remove_routing_path("joplin.token")
    assert "token" not in load_routing()["joplin"]
    assert load_routing()["joplin"]["host"] == "h"
