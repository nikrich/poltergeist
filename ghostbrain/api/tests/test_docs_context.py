"""A5: vault context for "draft from my vault"."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.api.repo import docs_context
from ghostbrain.api.repo import search as search_repo
from ghostbrain.vault_index.links import get_link_index


def _w(vault: Path, rel: str, text: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _hits(*paths: str):
    def fake(q, limit=10, days=None):
        return {"query": q, "total": len(paths), "items": [
            {"path": p, "title": p, "snippet": "", "score": 0.9} for p in paths
        ]}
    return fake


@pytest.fixture
def notes(tmp_vault: Path) -> Path:
    _w(tmp_vault, "20-contexts/work/plan.md",
       "---\ntitle: Plan\n---\nsee [[20-contexts/work/risks|Risks]]\n")
    _w(tmp_vault, "20-contexts/work/risks.md",
       "---\ntitle: Risks\n---\nvendor delay is the top risk\n")
    _w(tmp_vault, "20-contexts/work/budget.md",
       "---\ntitle: Budget\n---\nbudget is 40k\n")
    _w(tmp_vault, "20-contexts/work/standup.md",
       "---\ntitle: Standup\n---\nplan review: [[20-contexts/work/plan]]\n")
    get_link_index().refresh()
    return tmp_vault


def test_search_hits_come_first_then_link_neighbours(notes, monkeypatch):
    monkeypatch.setattr(search_repo, "search", _hits("20-contexts/work/budget.md"))
    ctx = docs_context.gather("budget risks", current_path="20-contexts/work/plan.md")
    assert ctx.index("### Budget") < ctx.index("### Risks") < ctx.index("### Standup")
    assert "budget is 40k" in ctx
    assert "vendor delay is the top risk" in ctx
    assert "(20-contexts/work/plan.md)" not in ctx  # the note being edited is excluded


def test_a_broken_search_still_returns_link_neighbours(notes, monkeypatch):
    def boom(q, limit=10, days=None):
        raise RuntimeError("no embedding index")
    monkeypatch.setattr(search_repo, "search", boom)
    ctx = docs_context.gather("anything", current_path="20-contexts/work/plan.md")
    assert "### Risks" in ctx


def test_unreadable_and_duplicate_hits_are_skipped(notes, monkeypatch):
    monkeypatch.setattr(search_repo, "search", _hits(
        "../outside.md", "20-contexts/work/gone.md",
        "20-contexts/work/budget.md", "20-contexts/work/budget.md",
    ))
    ctx = docs_context.gather("q", current_path=None)
    assert ctx.count("### Budget") == 1
    assert "gone" not in ctx and "outside" not in ctx


def test_output_is_capped_per_note_and_in_total(tmp_vault, monkeypatch):
    paths = []
    for i in range(10):
        rel = f"20-contexts/work/n{i}.md"
        _w(tmp_vault, rel, f"---\ntitle: N{i}\n---\n" + "x" * 5000 + "\n")
        paths.append(rel)
    monkeypatch.setattr(search_repo, "search", _hits(*paths))
    ctx = docs_context.gather("q", current_path=None)
    assert len(ctx) <= docs_context.TOTAL_CHARS
    blocks = ctx.split("\n\n### ")
    assert 1 <= len(blocks) <= docs_context.MAX_NOTES
    assert all(len(b) <= docs_context.PER_NOTE_CHARS + 60 for b in blocks)


def test_nothing_to_go_on_is_empty(tmp_vault):
    assert docs_context.gather("", current_path=None) == ""


def test_a_backslash_current_path_is_treated_as_posix(notes, monkeypatch):
    monkeypatch.setattr(search_repo, "search", _hits("20-contexts/work/plan.md"))
    ctx = docs_context.gather("q", current_path="20-contexts\\work\\plan.md")
    assert "### Risks" in ctx  # link neighbours found under the posix key
    assert "(20-contexts/work/plan.md)" not in ctx  # and the note itself excluded
