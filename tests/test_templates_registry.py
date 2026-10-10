"""Listing and loading templates from 90-meta/templates/."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from ghostbrain.templates.registry import (
    TEMPLATES_REL,
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


posix_non_root = pytest.mark.skipif(
    sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="permission bits are not enforced on Windows or for root",
)


@posix_non_root
def test_unreadable_template_is_listed_invalid_not_fatal(tmp_path: Path):
    _put(tmp_path, "weekly-review.md", OK)
    locked = _put(tmp_path, "locked.md", OK)
    locked.chmod(0)
    try:
        infos = {i.id: i for i in list_templates(tmp_path)}
        assert infos["weekly-review"].valid
        assert infos["locked"].diagnostics[0].code == "read"
        with pytest.raises(TemplateInvalid) as e:
            load_template("locked", tmp_path)
        assert e.value.diagnostics[0].code == "read"
    finally:
        locked.chmod(0o644)


@posix_non_root
def test_read_only_vault_lists_without_seeding(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    vault.chmod(0o500)
    try:
        assert list_templates(vault) == []
    finally:
        vault.chmod(0o755)
    assert not (vault / "90-meta").exists()


def test_symlink_loop_lists_nothing_and_loads_nothing(tmp_path: Path):
    meta = tmp_path / "90-meta"
    try:
        os.symlink(meta, meta)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")
    assert list_templates(tmp_path) == []
    with pytest.raises(TemplateNotFound):
        load_template("weekly-review", tmp_path)


def test_id_must_match_the_file_name_exactly(tmp_path: Path):
    _put(tmp_path, "Upper.md", OK)
    assert [i.diagnostics[0].code for i in list_templates(tmp_path)] == ["file-name"]
    with pytest.raises(TemplateNotFound):
        load_template("upper", tmp_path)
    with pytest.raises(TemplateNotFound):
        read_template_source("upper", tmp_path)


def test_oversized_file_is_rejected_without_reading_it_whole(tmp_path: Path, monkeypatch):
    from ghostbrain.templates import registry

    monkeypatch.setattr(registry, "MAX_TEMPLATE_BYTES", len(OK) - 1)
    _put(tmp_path, "weekly-review.md", OK)
    with pytest.raises(TemplateInvalid) as e:
        load_template("weekly-review", tmp_path)
    assert e.value.diagnostics[0].code == "limit"
    assert TEMPLATES_REL == "90-meta/templates"


@posix_non_root
def test_unsearchable_templates_folder_lists_and_loads_nothing(tmp_path: Path):
    _put(tmp_path, "weekly-review.md", OK)
    folder = tmp_path / TEMPLATES_REL
    folder.chmod(0o400)  # readable (listdir works) but not searchable (stat fails)
    try:
        assert list_templates(tmp_path) == []
        with pytest.raises(TemplateNotFound):
            load_template("weekly-review", tmp_path)
    finally:
        folder.chmod(0o755)
