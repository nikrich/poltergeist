"""Create-only writers on the vault write path: never overwrite, actors."""
from __future__ import annotations

from datetime import datetime, timezone

from ghostbrain import vault_write
from ghostbrain.api.repo import chat_attachments, generated_docs

HTML = "<!doctype html><html><body><h1>Q3</h1></body></html>"


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: D401 — fixed clock
        return datetime(2026, 10, 9, 10, 0, 0, tzinfo=timezone.utc)


def test_same_second_same_title_docs_do_not_overwrite(tmp_vault, monkeypatch):
    monkeypatch.setattr(generated_docs, "datetime", _Frozen)
    a = generated_docs.write_doc("Q3 One-Pager", HTML)
    b = generated_docs.write_doc("Q3 One-Pager", HTML.replace("Q3", "Q4"))
    assert a["path"] == "20-contexts/generated-docs/20261009T100000-q3-one-pager.html"
    assert b["path"] == "20-contexts/generated-docs/20261009T100000-q3-one-pager-2.html"
    assert (tmp_vault / a["path"]).read_text() == HTML  # verbatim, untouched


def test_write_doc_is_attributed_to_mcp(tmp_vault, monkeypatch):
    actors: list[str] = []
    real = vault_write.write_new
    monkeypatch.setattr(
        vault_write, "write_new",
        lambda rel, content, **kw: actors.append(kw["actor"]) or real(rel, content, **kw),
    )
    generated_docs.write_doc("t", HTML)
    assert actors == ["mcp"]


def test_attachment_note_collision_does_not_overwrite(tmp_vault, monkeypatch):
    monkeypatch.setattr(chat_attachments, "datetime", _Frozen)
    a = chat_attachments.save_attachment("c1", "notes.txt", "text/plain", b"first file")
    b = chat_attachments.save_attachment("c1", "notes.txt", "text/plain", b"second file")
    assert a["path"] != b["path"]
    assert b["path"].endswith("-notes-2.md")
    assert "first file" in (tmp_vault / a["path"]).read_text()


def test_attachment_note_bytes_and_actor(tmp_vault, monkeypatch):
    actors: list[str] = []
    real = vault_write.write_new
    monkeypatch.setattr(
        vault_write, "write_new",
        lambda rel, content, **kw: actors.append(kw["actor"]) or real(rel, content, **kw),
    )
    res = chat_attachments.save_attachment("c1", "plan.md", "text/markdown", b"# Plan\n")
    text = (tmp_vault / res["path"]).read_text()
    assert text.startswith("---\nid: ") and text.endswith("\n\n# Plan\n")
    assert actors == ["user"]
