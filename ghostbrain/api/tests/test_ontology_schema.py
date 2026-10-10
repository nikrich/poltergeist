from pathlib import Path

import pytest

from ghostbrain import paths
from ghostbrain.ontology import schema


def test_ontology_dir_default_under_home(monkeypatch, tmp_path):
    monkeypatch.delenv("GHOSTBRAIN_ONTOLOGY_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.ontology_dir() == tmp_path / "ghostbrain" / "ontology"


def test_ontology_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_ONTOLOGY_DIR", str(tmp_path / "x"))
    assert paths.ontology_dir() == tmp_path / "x"


def test_allowlists_are_disjoint_and_complete():
    assert not set(schema.CORE_KINDS) & set(schema.DOMAIN_KINDS)
    assert set(schema.RELATION_TYPES) <= set(schema.EDGE_TYPES)
    assert "Meta" in schema.VERTEX_TYPES
    assert {"PART_OF", "EVIDENCED_BY", "ABOUT", "IN", "WORKS_IN"} <= set(schema.EDGE_TYPES)


def test_ui_kind_covers_every_non_meta_vertex():
    for kind in schema.VERTEX_TYPES:
        if kind == "Meta":
            continue
        assert schema.ui_kind(kind).islower()
    assert schema.ui_kind("OpenQuestion") == "question"


@pytest.mark.parametrize("bad", ["Rule) DETACH DELETE (n", "", "rule"])
def test_check_kind_rejects_unknown(bad):
    with pytest.raises(ValueError):
        schema.check_kind(bad)


@pytest.mark.parametrize("bad", ["Name", "a-b", "x; MATCH", "1abc", ""])
def test_check_prop_rejects_non_identifiers(bad):
    with pytest.raises(ValueError):
        schema.check_prop(bad)


def test_topic_kinds_edges_and_event():
    assert "Topic" in schema.VERTEX_TYPES and schema.ui_kind("Topic") == "topic"
    assert {"IN_SCOPE", "OUT_OF_SCOPE", "HAS_TOPIC"} <= set(schema.EDGE_TYPES)
    assert "scope" in schema.EVENT_TYPES
