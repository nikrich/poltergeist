import io
from pathlib import Path

import pytest

from ghostbrain.api.repo import chat_attachments as repo
from ghostbrain.api.repo.attachment_extract import DOCX_MIME as repo_ex_DOCX_MIME


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


def test_title_for_path_reads_original_filename_from_frontmatter(tmp_vault: Path):
    result = repo.save_attachment("c", "notes.txt", "text/plain", b"hi")
    assert repo.title_for_path(result["path"]) == "notes.txt"


def test_title_for_path_falls_back_to_basename_when_unreadable(tmp_vault: Path):
    assert (
        repo.title_for_path("20-contexts/chat-attachments/missing.md") == "missing.md"
    )


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


# A minimal single-page PDF drawing "Hello PDF world" via a BT/Tj text object.
# pypdf logs a recoverable "incorrect startxref" warning and still extracts —
# that warning is expected and harmless.
MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>endobj
4 0 obj<</Length 58>>stream
BT /F1 24 Tf 72 700 Td (Hello PDF world) Tj ET
endstream endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000052 00000 n
0000000101 00000 n
0000000209 00000 n
0000000317 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
388
%%EOF"""


def _docx_bytes(*paragraphs: str) -> bytes:
    from docx import Document

    d = Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_saves_pdf_note_with_extracted_text(tmp_vault):
    result = repo.save_attachment("c", "report.pdf", "application/pdf", MINIMAL_PDF)
    assert result["kind"] == "pdf"
    assert result["title"] == "report.pdf"
    body = (tmp_vault / result["path"]).read_text(encoding="utf-8")
    assert "kind: pdf" in body
    assert "Hello PDF world" in body


def test_saves_docx_note_with_extracted_text(tmp_vault):
    data = _docx_bytes("Hello DOCX world")
    result = repo.save_attachment("c", "notes.docx", repo_ex_DOCX_MIME, data)
    assert result["kind"] == "docx"
    assert "Hello DOCX world" in (tmp_vault / result["path"]).read_text(encoding="utf-8")


def test_pdf_over_doc_cap_rejected(tmp_vault):
    big = MINIMAL_PDF + b"%" + b"a" * (repo.MAX_DOC_BYTES)
    with pytest.raises(repo.AttachmentTooLarge):
        repo.save_attachment("c", "big.pdf", "application/pdf", big)


def test_scanned_pdf_no_text_rejected(tmp_vault):
    # A structurally-valid PDF with no text content → UnsupportedAttachment.
    with pytest.raises(repo.UnsupportedAttachment):
        repo.save_attachment("c", "scan.pdf", "application/pdf", b"%PDF-1.4\n%%EOF")


def test_pdf_reuse_preserves_kind(tmp_vault):
    a = repo.save_attachment("c", "r.pdf", "application/pdf", MINIMAL_PDF)
    b = repo.save_attachment("c", "r.pdf", "application/pdf", MINIMAL_PDF)
    assert a["path"] == b["path"]
    assert b["kind"] == "pdf"


def test_kind_for_path(tmp_vault):
    result = repo.save_attachment("c", "r.pdf", "application/pdf", MINIMAL_PDF)
    assert repo.kind_for_path(result["path"]) == "pdf"
    assert (
        repo.kind_for_path("20-contexts/chat-attachments/missing.md") == "text"
    )
