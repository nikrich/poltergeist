"""save_note_body — frontmatter-preserving body rewrite for the rich editor."""
import frontmatter
import pytest

from ghostbrain.api.repo.note import (
    NoteInvalidPath,
    NoteNotFound,
    save_note_body,
)
from ghostbrain.api.tests.conftest import write_note

SYNCED = (
    "---\n"
    "source: gmail\n"
    "context: sanlam\n"
    "tags:\n"
    "- mail\n"
    "updated: '2026-01-01T00:00:00+00:00'\n"
    "---\n"
    "\n"
    "old body\n"
)


def test_save_rewrites_body_and_preserves_frontmatter(tmp_vault):
    write_note(tmp_vault, "20-contexts/sanlam/notes/synced.md", SYNCED)
    result = save_note_body("20-contexts/sanlam/notes/synced.md", "# edited\n\nnew body")
    post = frontmatter.load(tmp_vault / "20-contexts/sanlam/notes/synced.md")
    assert post.content.strip() == "# edited\n\nnew body"
    # connector-managed file: every frontmatter key survives untouched
    assert post["source"] == "gmail"
    assert post["context"] == "sanlam"
    assert post["tags"] == ["mail"]
    assert result["path"] == "20-contexts/sanlam/notes/synced.md"


def test_save_bumps_updated_when_key_exists(tmp_vault):
    write_note(tmp_vault, "20-contexts/sanlam/notes/synced.md", SYNCED)
    result = save_note_body("20-contexts/sanlam/notes/synced.md", "new body")
    post = frontmatter.load(tmp_vault / "20-contexts/sanlam/notes/synced.md")
    assert post["updated"] != "2026-01-01T00:00:00+00:00"
    assert result["updated"] == post["updated"]


def test_save_does_not_invent_updated_key(tmp_vault):
    write_note(
        tmp_vault,
        "20-contexts/personal/notes/no-updated.md",
        "---\nsource: manual\n---\n\nbody\n",
    )
    result = save_note_body("20-contexts/personal/notes/no-updated.md", "rewritten")
    post = frontmatter.load(tmp_vault / "20-contexts/personal/notes/no-updated.md")
    assert "updated" not in post.metadata
    assert result["updated"] is None


def test_save_plain_file_stays_frontmatter_free(tmp_vault):
    # frontmatter.dumps with empty metadata would emit a literal `---\n{}\n---`
    # block — the repo fn must special-case this (verified hazard).
    write_note(tmp_vault, "10-daily/2026-06-09.md", "plain body, no frontmatter\n")
    save_note_body("10-daily/2026-06-09.md", "rewritten")
    raw = (tmp_vault / "10-daily/2026-06-09.md").read_text()
    assert raw == "rewritten\n"
    assert "---" not in raw


def test_save_unknown_path_raises(tmp_vault):
    with pytest.raises(NoteNotFound):
        save_note_body("20-contexts/sanlam/notes/missing.md", "x")


def test_save_traversal_rejected(tmp_vault):
    with pytest.raises(NoteInvalidPath):
        save_note_body("../../etc/passwd.md", "x")


def test_save_non_md_rejected(tmp_vault):
    with pytest.raises(NoteInvalidPath):
        save_note_body("20-contexts/sanlam/notes/script.sh", "x")
