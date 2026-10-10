"""create_from_template writes through vault_write as the user; preview writes nothing."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from ghostbrain import vault_write
from ghostbrain.templates import env as env_mod
from ghostbrain.templates.create import create_from_template, preview_from_template
from ghostbrain.templates.render import RenderEnv
from ghostbrain.templates.starters import seed_starter_templates

NOW = datetime(2026, 10, 9, 14, 30, tzinfo=timezone(timedelta(hours=2)))
ENV = RenderEnv(now=NOW, default_context="work", contexts=("work", "personal"))


@pytest.fixture
def tpl_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(root))
    seed_starter_templates(root)
    return root


def _files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_create_writes_through_the_write_path_as_user(tpl_vault: Path, monkeypatch):
    calls = []
    real = vault_write.write_new

    def spy(rel_path, content, *, actor, reason="", max_attempts=100):
        calls.append((rel_path, actor, reason))
        return real(rel_path, content, actor=actor, reason=reason, max_attempts=max_attempts)

    monkeypatch.setattr("ghostbrain.templates.create.vault_write.write_new", spy)
    created = create_from_template("meeting-notes", {"topic": "Planning"}, env=ENV)
    assert created.path == "20-contexts/work/meetings/2026-10-09-planning.md"
    assert (created.title, created.status) == ("2026-10-09 Planning", "applied")
    assert created.etag
    assert calls == [(created.path, "user", "new note from template meeting-notes")]
    text = (tpl_vault / created.path).read_text(encoding="utf-8")
    head, body = text[4:].split("---\n\n", 1)
    assert yaml.safe_load(head)["fromTemplate"] == "meeting-notes"
    assert body.startswith("# Planning — 9 Oct 2026\n")


def test_second_create_same_day_gets_suffix_never_overwrites(tpl_vault: Path):
    first = create_from_template("meeting-notes", {"topic": "Planning"}, env=ENV)
    original = (tpl_vault / first.path).read_bytes()
    second = create_from_template("meeting-notes", {"topic": "Planning"}, env=ENV)
    assert second.path == "20-contexts/work/meetings/2026-10-09-planning-2.md"
    assert (tpl_vault / first.path).read_bytes() == original


def test_preview_writes_nothing(tpl_vault: Path):
    before = _files(tpl_vault)
    note = preview_from_template("one-on-one", {"person": "Alex"}, env=ENV)
    assert note.path == "20-contexts/work/one-on-ones/2026-10-09-alex-1-1.md"
    assert _files(tpl_vault) == before


def test_build_env_reads_contexts_projects_and_user(tpl_vault: Path, monkeypatch):
    (tpl_vault / "90-meta/routing.yaml").write_text("contexts:\n  - work\n  - personal\n", encoding="utf-8")
    (tpl_vault / "90-meta/projects.json").write_text(json.dumps([
        {"id": "work/alpha", "context": "work", "slug": "alpha", "name": "Alpha",
         "description": "", "archived": False, "created_at": 0},
    ]), encoding="utf-8")
    (tpl_vault / "90-meta/config.yaml").write_text("user:\n  name: Sam\n", encoding="utf-8")
    monkeypatch.setattr(env_mod, "_now", lambda: NOW)
    env = env_mod.build_env()
    assert (env.now, env.default_context, env.contexts, env.user_name) == (NOW, "work", ("work", "personal"), "Sam")
    assert env.projects["work/alpha"].name == "Alpha"


def test_build_env_without_config_has_empty_user(tpl_vault: Path):
    assert env_mod.build_env().user_name == ""


def test_person_title_uses_a_ready_index_only(tpl_vault: Path, monkeypatch):
    class Ready:
        ready = True

        def ensure_fresh(self, wait=0.25):
            return True

        def get(self, path):
            return SimpleNamespace(title="Alex Smith") if path == "30-cross-context/people/alex.md" else None

    class Cold(Ready):
        ready = False

    monkeypatch.setattr(env_mod, "get_link_index", lambda: Ready())
    assert env_mod.build_env().person_title("30-cross-context/people/alex.md") == "Alex Smith"
    monkeypatch.setattr(env_mod, "get_link_index", lambda: Cold())
    assert env_mod.build_env().person_title("30-cross-context/people/alex.md") is None


@pytest.mark.parametrize("raw", [
    b"user:\n  name: \xff\xfe\n",
    ("[" * 20000 + "]" * 20000).encode(),
    b"user:\n  name: Sam\n" + b"#" * (70 * 1024),
], ids=["bad-utf8", "deep-nesting", "oversize"])
def test_build_env_bad_config_gives_empty_user(tpl_vault: Path, raw: bytes):
    (tpl_vault / "90-meta/config.yaml").write_bytes(raw)
    assert env_mod.build_env().user_name == ""


@pytest.mark.parametrize("raw", [
    json.dumps([1, {"id": "work/alpha", "context": "work", "slug": "alpha", "name": "Alpha"}]).encode(),
    b"[\xff\xfe]",
    b"[" * 200000 + b"]" * 200000,
], ids=["non-dict-row", "invalid-bytes", "deep-nesting"])
def test_build_env_broken_projects_registry_gives_no_projects(tpl_vault: Path, raw: bytes):
    (tpl_vault / "90-meta/projects.json").write_bytes(raw)
    assert env_mod.build_env().projects == {}
