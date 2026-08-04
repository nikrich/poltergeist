"""Tests for the indexed-item count surfaced in the connector detail panel.

The UI showed "INDEXED 0" for every connector because the API returned
a hardcoded 0. These tests pin the real count: inbox + per-context
subdirs, with the directory-name remapping for connectors that don't
match their id verbatim (claude_code → claude/).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.api.repo import connectors as conn_repo


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fake vault so we can probe the count function in isolation."""
    monkeypatch.setattr("ghostbrain.paths.vault_path", lambda: tmp_path)
    return tmp_path


def _touch(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# stub\n", encoding="utf-8")


def test_count_zero_when_vault_is_empty(vault: Path) -> None:
    assert conn_repo._count_indexed("slack") == 0


def test_count_picks_up_inbox_files(vault: Path) -> None:
    _touch(vault / "00-inbox" / "raw" / "slack" / "msg-1.md")
    _touch(vault / "00-inbox" / "raw" / "slack" / "msg-2.md")
    assert conn_repo._count_indexed("slack") == 2


def test_count_picks_up_context_files(vault: Path) -> None:
    _touch(vault / "20-contexts" / "work" / "slack" / "msg-1.md")
    _touch(vault / "20-contexts" / "personal" / "slack" / "msg-2.md")
    assert conn_repo._count_indexed("slack") == 2


def test_count_combines_inbox_and_contexts(vault: Path) -> None:
    """The "INDEXED" stat is total reach across both staging and routed
    notes — anything below the connector's name in the vault."""
    _touch(vault / "00-inbox" / "raw" / "slack" / "a.md")
    _touch(vault / "20-contexts" / "work" / "slack" / "b.md")
    _touch(vault / "20-contexts" / "consulting" / "slack" / "c.md")
    assert conn_repo._count_indexed("slack") == 3


def test_count_recurses_into_nested_subdirs(vault: Path) -> None:
    """github stores PRs and issues in subfolders — rglob has to catch
    both or the count under-reports by half."""
    _touch(vault / "20-contexts" / "work" / "github" / "prs" / "p1.md")
    _touch(vault / "20-contexts" / "work" / "github" / "prs" / "p2.md")
    _touch(vault / "20-contexts" / "work" / "github" / "issues" / "i1.md")
    assert conn_repo._count_indexed("github") == 3


def test_claude_code_uses_remapped_dirs(vault: Path) -> None:
    """claude_code id doesn't match either dir name on disk:
    inbox writes to ``claude-code/`` (hyphenated), per-context writes
    to ``claude/`` (no suffix). The remap dicts must cover both."""
    _touch(vault / "00-inbox" / "raw" / "claude-code" / "session-1.md")
    _touch(vault / "20-contexts" / "consulting" / "claude" / "session-2.md")
    _touch(vault / "20-contexts" / "work" / "claude" / "session-3.md")
    assert conn_repo._count_indexed("claude_code") == 3


def test_count_ignores_non_md_files(vault: Path) -> None:
    _touch(vault / "00-inbox" / "raw" / "slack" / "msg.md")
    (vault / "00-inbox" / "raw" / "slack" / "msg.json").write_text("{}")
    (vault / "00-inbox" / "raw" / "slack" / "msg.wav").write_text("audio")
    assert conn_repo._count_indexed("slack") == 1


def test_connector_record_surfaces_real_count(vault: Path) -> None:
    """End-to-end via the public connector record builder — the field
    the UI binds to actually carries the count, not a hardcoded 0."""
    for i in range(5):
        _touch(vault / "20-contexts" / "work" / "slack" / f"m{i}.md")
    record = conn_repo._connector_record("slack")
    assert record["count"] == 5
    assert record["id"] == "slack"
