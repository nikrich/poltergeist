"""In-memory stand-ins for the Drive v3 / Docs v1 / Sheets v4 discovery clients.

They mimic the ``service.x().y(**kw).execute()`` call shape. ``FakeDrive``
honours the ``modifiedTime`` window in ``q`` and ``pageSize``/``pageToken`` so
paging and cursor logic run for real.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import httplib2
from googleapiclient.errors import HttpError

from ghostbrain.connectors.gdrive import drive as drive_mod


def http_error(status: int, reason: str, message: str = "boom") -> HttpError:
    resp = httplib2.Response({"status": str(status)})
    resp.reason = message
    content = json.dumps(
        {"error": {"code": status, "message": message,
                   "errors": [{"reason": reason, "message": message}]}}
    ).encode()
    return HttpError(resp, content)


def drive_file(fid: str, name: str = "Doc", *, mime: str = drive_mod.GDOC,
               modified: str = "2026-09-01T10:00:00.000Z", owned: bool = True,
               modified_by_me: bool = True, size: int | None = None,
               parents: list[str] | None = None) -> dict:
    f = {
        "id": fid, "name": name, "mimeType": mime, "modifiedTime": modified,
        "ownedByMe": owned, "modifiedByMe": modified_by_me,
        "owners": [{"emailAddress": "me@x.com", "displayName": "Me"}],
        "webViewLink": f"https://docs.google.com/d/{fid}",
        "parents": parents or [],
        "lastModifyingUser": {"emailAddress": "me@x.com", "displayName": "Me"},
    }
    if size is not None:
        f["size"] = str(size)
    return f


class _Req:
    def __init__(self, owner, fn):
        self._owner, self._fn = owner, fn

    def execute(self):
        if self._owner.fail_next:
            raise self._owner.fail_next.pop(0)
        return self._fn()


def _window(q: str) -> tuple[datetime | None, datetime | None]:
    def grab(op: str):
        m = re.search(rf"modifiedTime {op} '([^']+)'", q)
        return drive_mod.parse_time(m.group(1)) if m else None
    return grab(">"), grab("<")


class FakeDrive:
    def __init__(self, files: list[dict] | None = None):
        self.file_list = list(files or [])
        self.exports: dict[str, bytes] = {}
        self.too_big_exports: set[str] = set()
        self.media: dict[str, bytes] = {}
        self.folders: dict[str, dict] = {}
        self.list_calls: list[dict] = []
        self.fail_next: list[Exception] = []

    def files(self):
        return self

    def list(self, **kw):
        self.list_calls.append(kw)

        def run():
            after, before = _window(kw.get("q", ""))
            hits = [
                f for f in self.file_list
                if (after is None or drive_mod.parse_time(f["modifiedTime"]) > after)
                and (before is None or drive_mod.parse_time(f["modifiedTime"]) < before)
            ]
            hits.sort(key=lambda f: f["modifiedTime"], reverse=True)
            start = int(kw.get("pageToken") or 0)
            size = kw.get("pageSize", 100)
            page = hits[start:start + size]
            out = {"files": page}
            if start + size < len(hits):
                out["nextPageToken"] = str(start + size)
            return out
        return _Req(self, run)

    def export(self, fileId, mimeType):
        def run():
            if fileId in self.too_big_exports:
                raise http_error(403, "exportSizeLimitExceeded")
            return self.exports[fileId]
        return _Req(self, run)

    def get(self, fileId, fields=None, supportsAllDrives=None):
        return _Req(self, lambda: self.folders[fileId])

    def get_media(self, fileId, supportsAllDrives=None):
        return _Req(self, lambda: self.media[fileId])


class FakeDocs:
    def __init__(self, docs: dict[str, dict] | None = None):
        self.docs = docs or {}
        self.fail_next: list[Exception] = []

    def documents(self):
        return self

    def get(self, documentId):
        return _Req(self, lambda: self.docs[documentId])


class FakeSheets:
    """``sheets``: {spreadsheetId: {tab title: rows}}; ``grid``: optional
    {spreadsheetId: {tab title: (rowCount, columnCount)}}."""

    def __init__(self, sheets: dict[str, dict[str, list[list]]] | None = None,
                 grid: dict[str, dict[str, tuple[int, int]]] | None = None):
        self.sheets = sheets or {}
        self.grid = grid or {}
        self.batch_calls: list[dict] = []
        self.fail_next: list[Exception] = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, spreadsheetId, fields=None):
        def run():
            tabs = self.sheets[spreadsheetId]
            grid = self.grid.get(spreadsheetId, {})
            return {"sheets": [
                {"properties": {"title": t, "gridProperties": {
                    "rowCount": grid.get(t, (len(rows), 26))[0],
                    "columnCount": grid.get(t, (len(rows), 26))[1]}}}
                for t, rows in tabs.items()
            ]}
        return _Req(self, run)

    def batchGet(self, spreadsheetId, ranges, valueRenderOption=None):
        self.batch_calls.append({"spreadsheetId": spreadsheetId, "ranges": ranges})

        def run():
            tabs = self.sheets[spreadsheetId]
            out = []
            for r in ranges:
                title = r.rsplit("!", 1)[0][1:-1].replace("''", "'")
                rows = tabs[title]
                vr = {"range": r}
                if rows:
                    vr["values"] = [row[:50] for row in rows[:5000]]
                out.append(vr)
            return {"valueRanges": out}
        return _Req(self, run)


def fake_services(drive=None, docs=None, sheets=None) -> drive_mod.Services:
    return drive_mod.Services(drive=drive or FakeDrive(), docs=docs or FakeDocs(),
                              sheets=sheets or FakeSheets())


def install_fake_download(monkeypatch, fake: FakeDrive) -> None:
    def _dl(_drive, file_id: str, dest: Path) -> None:
        dest.write_bytes(fake.media[file_id])
    monkeypatch.setattr(drive_mod, "download", _dl)
