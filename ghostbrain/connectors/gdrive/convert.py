"""Drive file → Markdown body. Google Docs: Markdown export, Docs API over
10 MB. Google Sheets: Sheets API (no export limit, reads only the capped
range). Uploaded XLSX/PDF/DOCX: streamed to a temp file, then openpyxl or
the chat-attachment extractor."""
from __future__ import annotations

import dataclasses
import itertools
import tempfile
from pathlib import Path

from googleapiclient.errors import HttpError

from ghostbrain.api.repo import attachment_extract
from ghostbrain.connectors.gdrive import drive, tables
from ghostbrain.connectors.gdrive.docs_json import document_to_markdown

MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
MAX_BODY_CHARS = 1_000_000
EMPTY_BODY = "_No extractable text — open in Drive._"
_TRUNCATED_NOTE = "_…truncated (document continues in Drive)_"
_EXPORT_LIMIT = "exportSizeLimitExceeded"


class TooLarge(Exception):
    """File exceeds MAX_DOWNLOAD_BYTES; skipped without downloading."""


@dataclasses.dataclass
class ConvertResult:
    body: str
    truncated: bool


def cap_body(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_BODY_CHARS:
        return text, False
    cut = text.rfind("\n", 0, MAX_BODY_CHARS)
    if cut <= 0:
        cut = MAX_BODY_CHARS
    return text[:cut].rstrip() + "\n\n" + _TRUNCATED_NOTE, True


def convert(services: drive.Services, file: dict) -> ConvertResult:
    mime = file["mimeType"]
    truncated = False
    if mime == drive.GDOC:
        body = _doc(services, file)
    elif mime == drive.GSHEET:
        body, truncated = _sheet(services, file)
    elif mime == drive.XLSX:
        body, truncated = _downloaded(services, file, _xlsx)
    elif mime in (drive.PDF, drive.DOCX):
        body = _downloaded(services, file, _extracted)
    else:
        raise ValueError(f"unsupported mime type: {mime}")
    body, capped = cap_body(body)
    if not body.strip():
        body = EMPTY_BODY
    return ConvertResult(body=body, truncated=truncated or capped)


def _doc(services: drive.Services, file: dict) -> str:
    try:
        data = drive.execute(services.drive.files().export(fileId=file["id"], mimeType="text/markdown"))
    except HttpError as e:
        if _EXPORT_LIMIT not in drive.reasons(e):
            raise
        doc = drive.execute(services.docs.documents().get(documentId=file["id"]), api="Docs")
        return document_to_markdown(doc)
    return data.decode("utf-8") if isinstance(data, bytes) else str(data)


def _a1_range(title: str) -> str:
    return f"'{title.replace(chr(39), chr(39) * 2)}'!A1:{tables.MAX_COLS_A1}{tables.MAX_ROWS}"


def _sheet(services: drive.Services, file: dict) -> tuple[str, bool]:
    sid = file["id"]
    meta = drive.execute(services.sheets.spreadsheets().get(
        spreadsheetId=sid,
        fields="sheets.properties(title,sheetType,gridProperties(rowCount,columnCount))",
    ), api="Sheets")
    # Chart (OBJECT) and DATA_SOURCE tabs have no cells: an A1 range on one
    # fails the whole batchGet, so only GRID tabs (the default) are read.
    props = [s["properties"] for s in meta.get("sheets") or []
             if s["properties"].get("sheetType", "GRID") == "GRID"]
    shown = props[:tables.MAX_TABS]
    if not shown:
        return "", False
    resp = drive.execute(services.sheets.spreadsheets().values().batchGet(
        spreadsheetId=sid,
        ranges=[_a1_range(p["title"]) for p in shown],
        valueRenderOption="FORMATTED_VALUE",
    ), api="Sheets")
    tabs = []
    for p, vr in zip(shown, resp.get("valueRanges") or []):
        rows = vr.get("values") or []
        grid = p.get("gridProperties") or {}
        tabs.append(tables.Tab(
            name=p["title"],
            rows=rows,
            more_rows=grid.get("rowCount", 0) > tables.MAX_ROWS and len(rows) >= tables.MAX_ROWS,
            more_cols=grid.get("columnCount", 0) > tables.MAX_COLS
            and any(len(r) >= tables.MAX_COLS for r in rows),
        ))
    return tables.render_tables(tabs, extra_tabs=len(props) - len(shown))


def _downloaded(services: drive.Services, file: dict, reader):
    if int(file.get("size") or 0) > MAX_DOWNLOAD_BYTES:
        raise TooLarge(f"{file.get('name')} is {file.get('size')} bytes")
    with tempfile.TemporaryDirectory(prefix="gdrive-") as tmp:
        dest = Path(tmp) / "download"
        drive.download(services.drive, file["id"], dest)
        return reader(dest, file)


def _xlsx(path: Path, file: dict) -> tuple[str, bool]:
    import openpyxl

    # The temp file has no .xlsx suffix; openpyxl only skips its
    # extension check for a file-like object, so pass an open stream
    # rather than the path string.
    with path.open("rb") as fh:
        wb = openpyxl.load_workbook(fh, read_only=True, data_only=True)
        try:
            sheets = wb.worksheets
            tabs = [
                tables.Tab(ws.title, [list(r) for r in itertools.islice(
                    ws.iter_rows(values_only=True, max_col=tables.MAX_COLS + 1), tables.MAX_ROWS + 1)])
                for ws in sheets[:tables.MAX_TABS]
            ]
        finally:
            wb.close()
    return tables.render_tables(tabs, extra_tabs=max(0, len(sheets) - tables.MAX_TABS))


def _extracted(path: Path, file: dict) -> str:
    try:
        return attachment_extract.extract_text(file["name"], file["mimeType"], path)
    except attachment_extract.ExtractionError:
        return ""
