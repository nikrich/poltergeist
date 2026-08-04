"""Extract plain text from binary document attachments (PDF, .docx).

Pure-Python only (pypdf, python-docx) so the cpu-only Linux CI bundle stays
lean. Text attachments are handled directly in chat_attachments; this module
only knows about the binary document kinds.
"""
from __future__ import annotations

import io
from pathlib import Path

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ExtractionError(RuntimeError):
    """The document couldn't be read, or held no extractable text."""


def classify(filename: str, mime: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf" or mime == "application/pdf":
        return "pdf"
    if ext == ".docx" or mime == DOCX_MIME:
        return "docx"
    if ext == ".xlsx" or mime == XLSX_MIME:
        return "xlsx"
    return None


def extract_text(filename: str, mime: str, content: bytes) -> str:
    kind = classify(filename, mime)
    if kind == "pdf":
        text = _extract_pdf(content)
    elif kind == "docx":
        text = _extract_docx(content)
    elif kind == "xlsx":
        text = _extract_xlsx(content)
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


def _extract_xlsx(content: bytes) -> str:
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 — many corrupt-file exception types
        raise ExtractionError(f"could not read .xlsx: {e}") from e
    lines: list[str] = []
    for sheet in wb.worksheets:
        rows = [
            [("" if c is None else str(c)) for c in row]
            for row in sheet.iter_rows(values_only=True)
        ]
        rows = [r for r in rows if any(cell.strip() for cell in r)]
        if not rows:
            continue
        lines.append(f"## {sheet.title}")
        lines.extend(" | ".join(r) for r in rows)
    return "\n".join(lines)
