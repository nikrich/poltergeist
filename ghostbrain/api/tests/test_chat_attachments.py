from pathlib import Path

import pytest

from ghostbrain.api.repo import chat_attachments as repo


def test_saves_text_note_under_contexts(tmp_vault: Path):
    result = repo.save_attachment(
        "conv1", "notes.txt", "text/plain", b"hello world"
    )
    assert result["kind"] == "text"
    assert result["title"] == "notes.txt"
    assert result["path"].startswith("20-contexts/chat-attachments/")
    note = tmp_vault / result["path"]
    assert note.exists()
    text = note.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "source: chat-attachment" in text
    assert "conversation_id: conv1" in text
    assert "hello world" in text


def test_markdown_body_inlined_verbatim(tmp_vault: Path):
    result = repo.save_attachment("c", "a.md", "text/markdown", b"# Title\n\nBody")
    body = (tmp_vault / result["path"]).read_text(encoding="utf-8")
    assert "# Title\n\nBody" in body
    assert "```" not in body  # markdown is not fenced


def test_code_body_is_fenced_by_extension(tmp_vault: Path):
    result = repo.save_attachment("c", "s.py", "text/x-python", b"print(1)")
    body = (tmp_vault / result["path"]).read_text(encoding="utf-8")
    assert "```py\nprint(1)\n```" in body


def test_rejects_unsupported_type(tmp_vault: Path):
    with pytest.raises(repo.UnsupportedAttachment):
        repo.save_attachment("c", "x.png", "image/png", b"\x89PNG")


def test_rejects_oversize(tmp_vault: Path):
    big = b"a" * (repo.MAX_TEXT_BYTES + 1)
    with pytest.raises(repo.AttachmentTooLarge):
        repo.save_attachment("c", "big.txt", "text/plain", big)


def test_identical_content_reuses_note(tmp_vault: Path):
    a = repo.save_attachment("c", "d.txt", "text/plain", b"same")
    b = repo.save_attachment("c", "d.txt", "text/plain", b"same")
    assert a["path"] == b["path"]
    notes = list((tmp_vault / "20-contexts" / "chat-attachments").glob("*.md"))
    assert len(notes) == 1


def test_rejects_non_utf8_bytes(tmp_vault: Path):
    with pytest.raises(repo.UnsupportedAttachment):
        repo.save_attachment("c", "bad.txt", "text/plain", b"\xff\xfe\x00bad")


def test_reuse_returns_stored_title(tmp_vault: Path):
    a = repo.save_attachment("c", "first.txt", "text/plain", b"same")
    b = repo.save_attachment("c", "second.txt", "text/plain", b"same")
    assert b["path"] == a["path"]
    assert b["title"] == "first.txt"
    notes = list((tmp_vault / "20-contexts" / "chat-attachments").glob("*.md"))
    assert len(notes) == 1
