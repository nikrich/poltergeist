"""Starter templates: valid, render as advertised, seeded once, never overwritten."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ghostbrain.templates import registry, starters
from ghostbrain.templates.parse import parse_template
from ghostbrain.templates.render import RenderEnv, render
from ghostbrain.templates.starters import STARTER_TEMPLATES, seed_starter_templates

ENV = RenderEnv(now=datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2))),
                default_context="work", contexts=("work", "personal"))


def _tpl(name: str):
    r = parse_template(STARTER_TEMPLATES[name], name[:-3])
    assert r.ok and r.diagnostics == (), r.diagnostics
    return r.template


def test_the_three_starters():
    assert sorted(STARTER_TEMPLATES) == ["decision-record.md", "meeting-notes.md", "one-on-one.md"]
    assert [_tpl(n).name for n in sorted(STARTER_TEMPLATES)] == ["Decision record", "Meeting notes", "1-1"]


def test_one_on_one_renders_as_in_the_spec():
    note = render(_tpl("one-on-one.md"), {"person": "Alex"}, ENV)
    assert note.path == "20-contexts/work/one-on-ones/2026-10-09-alex-1-1.md"
    assert note.frontmatter["type"] == "meeting"
    assert note.frontmatter["attendees"] == ["[[Alex]]"]
    assert note.body.startswith("# 1-1 with [[Alex]] — 9 Oct 2026\n")
    assert '```query\ntype: action_item\nmentions: "[[Alex]]"\nstatus: open\nsort: created desc\n```' in note.body


def test_meeting_notes_renders():
    note = render(_tpl("meeting-notes.md"), {"topic": "Planning"}, ENV)
    assert note.path == "20-contexts/work/meetings/2026-10-09-planning.md"
    assert note.body.startswith("# Planning — 9 Oct 2026\n")
    assert "## Action items" in note.body


def test_decision_record_defaults():
    note = render(_tpl("decision-record.md"), {"decision": "Use Postgres for search"}, ENV)
    assert note.path == "20-contexts/work/decisions/2026-10-09-use-postgres-for-search.md"
    assert note.frontmatter["status"] == "accepted" and note.frontmatter["type"] == "decision"
    assert "**Project:** none" in note.body


def test_seed_writes_all_when_folder_missing(tmp_path: Path):
    written = seed_starter_templates(tmp_path)
    assert sorted(written) == [f"90-meta/templates/{n}" for n in sorted(STARTER_TEMPLATES)]
    for name, body in STARTER_TEMPLATES.items():
        assert (tmp_path / "90-meta/templates" / name).read_text(encoding="utf-8") == body
    assert seed_starter_templates(tmp_path) == []


def test_deleted_starter_is_not_reseeded(tmp_path: Path):
    seed_starter_templates(tmp_path)
    (tmp_path / "90-meta/templates/meeting-notes.md").unlink()
    assert seed_starter_templates(tmp_path) == []
    assert not (tmp_path / "90-meta/templates/meeting-notes.md").exists()


def test_seed_never_overwrites(tmp_path: Path):
    folder = tmp_path / "90-meta/templates"
    folder.mkdir(parents=True)
    (folder / "one-on-one.md").write_text("mine", encoding="utf-8")
    assert seed_starter_templates(tmp_path) == []
    assert (folder / "one-on-one.md").read_text(encoding="utf-8") == "mine"


def test_seed_never_writes_through_a_symlinked_meta_folder(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        os.symlink(elsewhere, vault / "90-meta")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")
    assert seed_starter_templates(vault) == []
    assert list(elsewhere.iterdir()) == []


def test_templates_path_is_defined_once():
    assert registry.TEMPLATES_REL is starters.TEMPLATES_REL
    assert "90-meta/templates" not in Path(registry.__file__).read_text(encoding="utf-8")


def test_seed_survives_a_symlink_loop(tmp_path: Path):
    meta = tmp_path / "90-meta"
    try:
        os.symlink(meta, meta)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")
    assert seed_starter_templates(tmp_path) == []


def test_starters_module_imports_no_pydantic():
    # bootstrap imports starters in base installs, which have no pydantic.
    code = ("import sys, ghostbrain.templates.starters, ghostbrain.bootstrap; "
            "assert 'pydantic' not in sys.modules, 'pydantic imported'")
    proc = subprocess.run([sys.executable, "-c", code], check=False,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def test_bootstrap_seeds_starters_and_keeps_edits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    from ghostbrain.bootstrap import bootstrap

    root = bootstrap(tmp_path)
    f = root / "90-meta/templates/one-on-one.md"
    assert f.read_text(encoding="utf-8") == STARTER_TEMPLATES["one-on-one.md"]
    f.write_text("edited", encoding="utf-8")
    bootstrap(tmp_path)
    assert f.read_text(encoding="utf-8") == "edited"
