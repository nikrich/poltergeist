from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ghostbrain import routing_config as rc

COMMENTED = """\
# Routing rules — hand edited
version: 1

# The vault's contexts.
contexts:
  - personal
  - work

# GitHub orgs → context.
github:
  orgs:
    acme: work   # keep this comment
gmail:
  sender_domains:
    acme.com: work
"""


@pytest.fixture
def v(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(COMMENTED, encoding="utf-8")
    return root


def _text(root: Path) -> str:
    return (root / "90-meta" / "routing.yaml").read_text(encoding="utf-8")


def test_add_context_preserves_everything_else(v):
    assert rc.add_context("agencyx", v) == ("personal", "work", "agencyx")
    text = _text(v)
    assert "contexts:\n  - personal\n  - work\n  - agencyx\n" in text
    before, after = COMMENTED.split("contexts:")[0], COMMENTED.split("# GitHub orgs")[1]
    assert text.startswith(before)
    assert text.endswith(after)
    assert "acme: work   # keep this comment" in text
    assert rc.contexts(v) == ("personal", "work", "agencyx")


def test_add_creates_context_folders(v):
    rc.add_context("agencyx", v)
    ctx = v / "20-contexts" / "agencyx"
    assert (ctx / "_index.md").exists() and (ctx / "_profile.md").exists()


def test_archive_and_restore(v):
    rc.add_context("agencyx", v)
    assert rc.archive_context("agencyx", v) == ("personal", "work")
    assert rc.archived_contexts(v) == ("agencyx",)
    assert "archived_contexts:\n  - agencyx\n" in _text(v)
    assert (v / "20-contexts" / "agencyx").exists()          # nothing deleted
    assert rc.add_context("agencyx", v) == ("personal", "work", "agencyx")  # restore
    assert rc.archived_contexts(v) == ()


@pytest.mark.parametrize("name", ["", "Agency X", "needs_review", "-x", "a" * 41, "x/y", "../up"])
def test_invalid_names_rejected(v, name):
    with pytest.raises(rc.ContextError):
        rc.add_context(name, v)
    assert _text(v) == COMMENTED


def test_duplicate_and_last_and_unknown(v):
    with pytest.raises(rc.ContextError):
        rc.add_context("work", v)
    rc.archive_context("work", v)
    with pytest.raises(rc.ContextError):
        rc.archive_context("personal", v)                    # last active
    with pytest.raises(rc.ContextError):
        rc.archive_context("nope", v)


def test_flow_style_contexts_rewritten(tmp_path):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(
        "contexts: [personal, work]\ngithub:\n  orgs: {}\n", encoding="utf-8")
    rc.add_context("agencyx", root)
    data = yaml.safe_load(_text(root))
    assert data["contexts"] == ["personal", "work", "agencyx"]
    assert data["github"] == {"orgs": {}}


def test_missing_contexts_key_uses_defaults_then_writes(tmp_path):
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text("github:\n  orgs: {}\n", encoding="utf-8")
    rc.add_context("agencyx", root)
    assert rc.contexts(root) == (*rc.DEFAULT_CONTEXTS, "agencyx")
