"""Template source: read with etag, save via the write path, blank create, query hints."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain import vault_write
from ghostbrain.templates.parse import parse_template
from ghostbrain.templates.registry import TEMPLATE_ID_RE, TemplateNotFound, list_templates
from ghostbrain.templates.source import (
    SourceTooLarge,
    blank_template,
    create_blank,
    query_values,
    read_source,
    save_source,
)
from ghostbrain.vault_write import USER, WriteConflict

OK = "---\ntemplate:\n  name: Weekly review\n---\n# Week {{date | format: D MMM}}\n"


@pytest.fixture
def vault(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "vault"
    (root / "90-meta/templates").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(root))
    return root


def _put(vault: Path, name: str, text: str) -> Path:
    p = vault / "90-meta/templates" / name
    p.write_text(text, encoding="utf-8")
    return p


def test_read_source_returns_text_and_the_write_path_etag(vault):
    _put(vault, "weekly.md", OK)
    src = read_source("weekly")
    assert (src.id, src.path, src.source) == ("weekly", "90-meta/templates/weekly.md", OK)
    assert src.etag == vault_write.current_etag("90-meta/templates/weekly.md")
    assert src.to_json() == {"id": "weekly", "path": src.path, "source": OK, "etag": src.etag}


def test_read_source_refuses_symlinks_and_bad_ids(vault, tmp_path):
    outside = tmp_path / "secret.md"
    outside.write_text(OK, encoding="utf-8")
    try:
        (vault / "90-meta/templates/link.md").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    for tid in ("link", "../secret", "Weekly", "missing"):
        with pytest.raises(TemplateNotFound):
            read_source(tid)


def test_save_replaces_the_file_with_the_matching_etag(vault):
    _put(vault, "weekly.md", OK)
    etag = read_source("weekly").etag
    new = OK.replace("Week", "Week of")
    res = save_source("weekly", new, actor=USER, base_etag=etag)
    assert res.status == "applied" and res.etag == read_source("weekly").etag
    assert (vault / "90-meta/templates/weekly.md").read_text(encoding="utf-8") == new
    assert res.to_json()["changeId"] is None


def test_save_with_a_stale_etag_conflicts_and_writes_nothing(vault):
    _put(vault, "weekly.md", OK)
    with pytest.raises(WriteConflict):
        save_source("weekly", "changed\n", actor=USER, base_etag="0000000000000000")
    assert (vault / "90-meta/templates/weekly.md").read_text(encoding="utf-8") == OK


def test_save_keeps_a_broken_template_so_it_can_be_fixed(vault):
    _put(vault, "weekly.md", OK)
    broken = "---\ntemplate:\n  name: [x\n---\n"
    save_source("weekly", broken, actor=USER, base_etag=None)
    [info] = [i for i in list_templates() if i.id == "weekly"]
    assert not info.valid


def test_save_refuses_unknown_ids_and_oversize_source(vault):
    with pytest.raises(TemplateNotFound):
        save_source("nope", OK, actor=USER, base_etag=None)
    _put(vault, "weekly.md", OK)
    with pytest.raises(SourceTooLarge):
        save_source("weekly", "x" * 256_001, actor=USER, base_etag=None)


def test_blank_template_parses_and_quotes_the_name():
    for name in ("Weekly review", 'Say "hi": now', "Ünïcödé ✓", "1-1"):
        result = parse_template(blank_template(name), "x")
        assert result.ok, result.diagnostics
        assert result.template.name == name
        assert result.diagnostics == ()


def test_create_blank_slugs_the_id_and_never_overwrites(vault):
    first = create_blank("Weekly Review", actor=USER)
    second = create_blank("Weekly review", actor=USER)
    assert (first.id, first.path) == ("weekly-review", "90-meta/templates/weekly-review.md")
    assert second.id == "weekly-review-2"
    assert parse_template(read_source("weekly-review").source, "weekly-review").ok


def test_create_blank_seeds_the_starters_when_the_folder_is_missing(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(root))
    create_blank("Retro", actor=USER)
    ids = sorted(i.id for i in list_templates())
    assert ids == ["decision-record", "meeting-notes", "one-on-one", "retro"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 81, "two\nlines"])
def test_create_blank_rejects_bad_names(vault, name):
    with pytest.raises(ValueError):
        create_blank(name, actor=USER)


def _note(vault: Path, rel: str, fm: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\n{fm}\n---\nbody\n", encoding="utf-8")


def test_create_blank_falls_back_to_a_safe_id_for_unsluggable_names(vault):
    res = create_blank("✓✓", actor=USER)
    assert TEMPLATE_ID_RE.fullmatch(res.id)
    assert res.path == f"90-meta/templates/{res.id}.md"
    assert read_source(res.id).id == res.id


def test_query_values_ranks_types_and_statuses_from_the_index(vault, monkeypatch):
    from ghostbrain.vault_index import links
    from ghostbrain.vault_index.links import get_link_index

    # A private index table: nothing outlives this test's tmp vault.
    monkeypatch.setattr(links, "_INDEXES", {})

    _note(vault, "20-contexts/work/a.md", "type: action_item\nstatus: Done")
    _note(vault, "20-contexts/work/b.md", "artifactType: action_item")
    _note(vault, "20-contexts/work/c.md", "type: decision\nstatus: open")
    _note(vault, "20-contexts/work/d.md", "type: meeting")
    assert query_values()["indexing"] is True  # cold: starts the build
    assert get_link_index().wait_until_ready(5.0)
    data = query_values()
    assert data["indexing"] is False
    assert data["types"][0] == "action_item" and set(data["types"]) == {"action_item", "decision", "meeting"}
    assert sorted(data["statuses"]) == ["done", "open"]
