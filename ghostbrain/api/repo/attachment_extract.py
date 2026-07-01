"""Extract plain text from binary document attachments (PDF, .docx).

Pure-Python only (pypdf, python-docx) so the cpu-only Linux CI bundle stays
lean. Text attachments are handled directly in chat_attachments; this module
only knows about the binary document kinds.
"""
from __future__ import annotations

import io
from pathlib import Path

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ExtractionError(RuntimeError):
    """The document couldn't be read, or held no extractable text."""


def classify(filename: str, mime: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf" or mime == "application/pdf":
        return "pdf"
    if ext == ".docx" or mime == DOCX_MIME:
        return "docx"
    return None


def extract_text(filename: str, mime: str, content: bytes) -> str:
    kind = classify(filename, mime)
    if kind == "pdf":
        text = _extract_pdf(content)
    elif kind == "docx":
        text = _extract_docx(content)
    else:
        raise ExtractionError(f"not an extractable document: {filename} ({mime})")
    if not text.strip():
        raise ExtractionError(
            f"no extractable text in {filename} (scanned or image-only?)"
        )
    return text


def _extract_pdf(content: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            # An empty-password decrypt succeeds for many "encrypted" PDFs.
            try:
                reader.decrypt("")
            except Exception as e:  # noqa: BLE001
                raise ExtractionError("PDF is password-protected") from e
        pages = [(page.extract_text() or "") for page in reader.pages]
    except ExtractionError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ExtractionError(f"could not read PDF: {e}") from e
    return "\n\n".join(p for p in pages if p.strip())


def _extract_docx(content: bytes) -> str:
    import docx
    from docx.opc.exceptions import PackageNotFoundError

    try:
        document = docx.Document(io.BytesIO(content))
    except (PackageNotFoundError, KeyError, ValueError, OSError) as e:
        raise ExtractionError(f"could not read .docx: {e}") from e
    return "\n".join(p.text for p in document.paragraphs if p.text.strip())
