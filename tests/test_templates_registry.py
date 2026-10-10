"""Listing and loading templates from 90-meta/templates/."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.templates.registry import (
    TemplateInvalid,
    TemplateNotFound,
    list_templates,
    load_template,
    read_template_source,
)

OK = "---\ntemplate:\n  name: Weekly review\n---\n# Week {{date | format: D MMM}}\n"
BROKEN = "---\ntemplate:\n  name: [unclosed\n---\n"


def _put(root: Path, name: str, text: str | bytes) -> Path:
    p = root / "90-meta/templates" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        p.write_bytes(text)
    else:
        p.write_text(text, encoding="utf-8")
    return p


def test_list_seeds_starters_when_folder_missing(tmp_path: Path):
    infos = list_templates(tmp_path)
    assert [i.template.name for i in infos] == ["1-1", "Decision record", "Meeting notes"]
    assert all(i.valid for i in infos)
    j = infos[0].to_json()
    assert j["id"] == "one-on-one" and j["path"] == "90-meta/templates/one-on-one.md"
    assert j["valid"] is True and j["diagnostics"] == []
    assert j["variables"] == ["context", "date", "focus", "person"]
    assert [p["id"] for p in j["prompts"]] == ["person", "focus"]


def test_empty_folder_is_not_seeded(tmp_path: Path):
    (tmp_path / "90-meta/templates").mkdir(parents=True)
    assert list_templates(tmp_path) == []


def test_list_keeps_valid_templates_next_to_broken_one(tmp_path: Path):
    _put(tmp_path, "weekly-review.md", OK)
    _put(tmp_path, "broken.md", BROKEN)
    infos = {i.id: i for i in list_templates(tmp_path)}
    assert infos["weekly-review"].valid
    bad = infos["broken"].to_json()
    assert bad["valid"] is False and bad["name"] == "broken" and bad["prompts"] == []
    assert bad["diagnostics"][0]["code"] == "yaml"


def test_bad_file_name_encoding_and_size_are_listed_invalid(tmp_path: Path):
    _put(tmp_path, "My Notes.md", OK)
    _put(tmp_path, "latin.md", "---\ntemplate:\n  name: caf\xe9\n---\n".encode("latin-1"))
    _put(tmp_path, "huge.md", OK + "a" * 1_100_000)
    _put(tmp_path, ".hidden.md", OK)
    _put(tmp_path, "notes.txt", OK)
    codes = {i.id: i.diagnostics[0].code for i in list_templates(tmp_path)}
    assert codes == {"My Notes": "file-name", "latin": "encoding", "huge": "limit"}


def test_load_and_read(tmp_path: Path):
    _put(tmp_path, "weekly-review.md", OK)
    assert read_template_source("weekly-review", tmp_path) == OK
    t = load_template("weekly-review", tmp_path)
    assert t.id == "weekly-review" and t.name == "Weekly review"


def test_load_unknown_and_invalid(tmp_path: Path):
    _put(tmp_path, "broken.md", BROKEN)
    with pytest.raises(TemplateNotFound):
        load_template("missing", tmp_path)
    with pytest.raises(TemplateInvalid) as e:
        load_template("broken", tmp_path)
    assert e.value.diagnostics[0].code == "yaml"
    assert str(e.value).startswith("line ")


def test_default_root_is_the_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    _put(tmp_path, "weekly-review.md", OK)
    assert load_template("weekly-review").name == "Weekly review"
