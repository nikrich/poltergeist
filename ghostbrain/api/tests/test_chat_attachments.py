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


import base64


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_upload_endpoint_writes_and_returns_paths(client, auth_headers):
    conv = client.post("/v1/chat", headers=auth_headers).json()
    res = client.post(
        f"/v1/chat/{conv['id']}/attachments",
        json={"files": [{"name": "n.txt", "mime": "text/plain",
                         "content_b64": _b64(b"hello")}]},
        headers=auth_headers,
    )
    assert res.status_code == 200
    atts = res.json()["attachments"]
    assert len(atts) == 1
    assert atts[0]["path"].startswith("20-contexts/chat-attachments/")


def test_upload_unknown_conversation_404(client, auth_headers):
    res = client.post(
        "/v1/chat/nope/attachments",
        json={"files": [{"name": "n.txt", "mime": "text/plain",
                         "content_b64": _b64(b"x")}]},
        headers=auth_headers,
    )
    assert res.status_code == 404


def test_upload_unsupported_type_415(client, auth_headers):
    conv = client.post("/v1/chat", headers=auth_headers).json()
    res = client.post(
        f"/v1/chat/{conv['id']}/attachments",
        json={"files": [{"name": "x.png", "mime": "image/png",
                         "content_b64": _b64(b"\x89PNG")}]},
        headers=auth_headers,
    )
    assert res.status_code == 415


def test_upload_too_many_files_400(client, auth_headers):
    conv = client.post("/v1/chat", headers=auth_headers).json()
    files = [{"name": f"f{i}.txt", "mime": "text/plain",
              "content_b64": _b64(b"x")} for i in range(11)]
    res = client.post(
        f"/v1/chat/{conv['id']}/attachments",
        json={"files": files}, headers=auth_headers,
    )
    assert res.status_code == 400
