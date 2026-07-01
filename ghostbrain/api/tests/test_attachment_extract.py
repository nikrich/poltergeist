import io

import pytest

from ghostbrain.api.repo import attachment_extract as ex


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


def test_classify():
    assert ex.classify("a.pdf", "application/pdf") == "pdf"
    assert ex.classify("a.PDF", "") == "pdf"
    assert ex.classify("a.docx", ex.DOCX_MIME) == "docx"
    assert ex.classify("a.docx", "") == "docx"
    assert ex.classify("a.txt", "text/plain") is None


def test_extract_pdf_text():
    out = ex.extract_text("a.pdf", "application/pdf", MINIMAL_PDF)
    assert "Hello PDF world" in out


def test_extract_docx_text():
    data = _docx_bytes("Hello DOCX world", "second line")
    out = ex.extract_text("a.docx", ex.DOCX_MIME, data)
    assert "Hello DOCX world" in out
    assert "second line" in out


def test_extract_corrupt_pdf_raises():
    with pytest.raises(ex.ExtractionError):
        ex.extract_text("a.pdf", "application/pdf", b"not a pdf at all")


def test_extract_empty_docx_raises():
    with pytest.raises(ex.ExtractionError):
        ex.extract_text("a.docx", ex.DOCX_MIME, _docx_bytes("", "   "))


def test_extract_unknown_kind_raises():
    with pytest.raises(ex.ExtractionError):
        ex.extract_text("a.txt", "text/plain", b"hi")
