# Google Drive Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `gdrive` connector that imports Google Docs, Google Sheets, PDF, DOCX and XLSX files the user owns or has edited — hourly incremental sync plus a resumable, UI-driven backfill — as one vault note per Drive file, updated in place.

**Architecture:** One `files.list` query shape windowed by `modifiedTime` feeds both the hourly `GdriveConnector` (per-account cursors, 30-min debounce) and the scheduler-ticked backfill job (month cursor walking backwards). Both call one `ingest_file()` that converts (Drive export / Docs API / Sheets API / openpyxl / pypdf / python-docx) and upserts into the vault by stable filename `<title-slug>-<fileId>.md` — new files go through the normal worker pipeline, changed files are rewritten in place keeping their context.

**Tech Stack:** Python 3.11+, google-api-python-client (Drive v3, Docs v1, Sheets v4), openpyxl, pypdf, python-docx, FastAPI, pytest; React + TanStack Query + Vitest in `desktop/`.

**Spec:** `docs/superpowers/specs/2026-09-28-gdrive-connector-design.md`

## Global Constraints

- Worktree: `/Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector`, branch `feat/gdrive-connector`. `cd` there in EVERY shell command and check `git rev-parse --abbrev-ref HEAD` prints `feat/gdrive-connector` before committing.
- Python tests: `.venv/bin/python -m pytest <path> -q -p no:cacheprovider`. The venv exists. The repo-root `conftest.py` sandboxes `HOME`, `GHOSTBRAIN_STATE_DIR` (= `<tmp_path>/state`) and `VAULT_PATH` (= `<tmp_path>/vault`) for every test; `paths.vault_path()` / `paths.state_dir()` read the env live.
- Baseline (not yours): full suite `.venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_recorder_wasapi_io.py` = **22 failed, 1428 passed** — failures only in `test_agent_stream`, `test_calendar`, `test_joplin_connector`, `test_mcp_integration`, `test_mcp_tools`, `test_recorder_api_platform_guard`, `test_recorder_audio_backend`, `test_recorder_platform_guard`, `test_semantic`, `test_weekly_digest`. A task is green when it adds no failures beyond these.
- Ruff: `.venv/bin/python -m ruff check <files you touched>` clean for new code.
- Desktop: `cd desktop && npx vitest run <file>`; typecheck with `npm run typecheck` (NOT `tsc --noEmit`, which is a no-op here).
- Connector id / source / account connector / state prefix: `gdrive` everywhere. Display name `Google Drive`.
- OAuth scope: exactly `https://www.googleapis.com/auth/drive.readonly`. Token file `<state>/gdrive.<slug>.token`, slug = email lowercased, `@`→`_at_`, `.`→`_`.
- Event id `gdrive:<fileId>` (one note per Drive file across accounts). Note filename `<title-slug>-<fileId>.md`.
- Caps: download 200 MB (`200 * 1024 * 1024`), body 1,000,000 chars, 5,000 rows × 50 columns (A1 `AX`) per tab, 50 tabs. Messages verbatim: `_…truncated at 5,000 rows_`, `_…truncated at 50 columns_`, `_…N more tabs_`, `_…truncated (document continues in Drive)_`, `_No extractable text — open in Drive._`.
- Sync: first-run lookback 7 days, debounce 30 minutes, every 1 h. Backfill: batch 25, tick every 120 s, max 10 years, estimate cap 5,000, UI pace 750 files/h.
- API-not-enabled message: `Enable the Google <API> API in Google Cloud for your OAuth client's project (APIs & Services → Library).` with `<API>` one of `Drive`, `Docs`, `Sheets`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **A doc renamed in Drive** — the note keeps its old filename and is still updated in place (lookup is by `-<fileId>.md` suffix, not title). Pinned in Task 5 (`test_upsert_updates_renamed_doc_under_old_filename`).
2. **The same shared doc edited from two connected accounts** — exactly one note, not two. Pinned in Task 5 (`test_same_file_from_two_accounts_is_one_note`).
3. **A sheet tab whose name contains a quote or spaces** (`Q3 'final'`) — A1 range is quoted/escaped so the Sheets API call doesn't 400. Pinned in Task 4 (`test_sheet_tab_names_are_quoted_in_ranges`).
4. **One account rate-limited while another syncs fine** — the healthy account's cursor advances, the limited one's does not. Pinned in Task 6 (`test_failing_account_keeps_its_cursor`).
5. **A file modified exactly at a month boundary during backfill** (`2026-08-01T00:00:00Z`) — imported once, not skipped between windows. Pinned in Task 7 (`test_month_boundary_file_is_included`).

---

## File Structure

```
ghostbrain/connectors/gdrive/
  __init__.py      exports GdriveConnector
  auth.py          scopes, token paths, credentials, OAuth flow   (Task 1)
  drive.py         services, query, paging, error mapping, folders, download  (Task 2)
  tables.py        rows → Markdown tables with caps               (Task 3)
  docs_json.py     Docs API document JSON → Markdown              (Task 4)
  convert.py       per-mime conversion + body cap                 (Task 4)
  event.py         file + ConvertResult → pipeline event          (Task 5)
  store.py         find notes by fileId, upsert/rewrite in place  (Task 5)
  ingest.py        convert + event + upsert for one file          (Task 6)
  connector.py     hourly GdriveConnector (per-account cursors)   (Task 6)
  runner.py        scheduler entry point                          (Task 6)
  backfill.py      resumable per-account backfill                 (Task 7)
tests/gdrive_fakes.py                    fake Drive/Docs/Sheets services (Task 2)
tests/test_gdrive_*.py                   one file per module
ghostbrain/api/tests/test_gdrive_*.py    auth wiring + routes
desktop/src/renderer/components/AccountBackfill.tsx   (Task 9)
```

Modified: `ghostbrain/accounts.py`, `ghostbrain/api/auth/providers/google_oauth.py`, `ghostbrain/api/auth/providers/register_all.py`, `ghostbrain/api/auth/disconnect.py`, `ghostbrain/api/repo/connector_probe.py`, `ghostbrain/api/repo/connectors.py`, `ghostbrain/api/repo/attachment_extract.py`, `ghostbrain/worker/note_generator.py`, `ghostbrain/scheduler_jobs.py`, `ghostbrain/api/routes/connectors.py`, `desktop/src/shared/api-types.ts`, `desktop/src/renderer/lib/api/hooks.ts`, `desktop/src/renderer/lib/connector-catalog.ts`, `desktop/src/renderer/components/ConnectorAccounts.tsx`, `docs/connectors.md`, `.claude/skills/poltergeist-setup/SKILL.md`, `.claude/skills/poltergeist-setup/checks.md`.

---

### Task 1: Auth module + account/connector registration

**Files:**
- Create: `ghostbrain/connectors/gdrive/__init__.py`, `ghostbrain/connectors/gdrive/auth.py`
- Modify: `ghostbrain/accounts.py:41-58`, `ghostbrain/api/auth/providers/google_oauth.py:13-19,103-104`, `ghostbrain/api/auth/providers/register_all.py:17-18`, `ghostbrain/api/auth/disconnect.py:38-43`, `ghostbrain/api/repo/connector_probe.py:125-128`, `ghostbrain/api/repo/connectors.py:9-83`
- Test: `tests/test_gdrive_auth.py`, `ghostbrain/api/tests/test_gdrive_wiring.py`

**Interfaces:**
- Produces: `auth.SCOPES: list[str]`, `auth.GdriveAuthError(RuntimeError)`, `auth.slug(email: str) -> str`, `auth.state_dir() -> Path`, `auth.oauth_client_path() -> Path`, `auth.token_path(email: str) -> Path`, `auth.load_credentials(email: str) -> google.oauth2.credentials.Credentials`, `auth.run_oauth_flow(email: str) -> Path`. Account connector `"gdrive"` in `accounts.ACCOUNT_CONNECTORS` and `accounts.SOURCE_TO_ACCOUNT_CONNECTOR["gdrive"] == "gdrive"`. `/v1/connectors` lists id `gdrive`, displayName `Google Drive`.

- [ ] **Step 1: Write the failing tests**

`tests/test_gdrive_auth.py`:

```python
from __future__ import annotations

import pytest


def test_slug_and_token_path():
    from ghostbrain.connectors.gdrive import auth

    assert auth.slug("You.Name@Gmail.com") == "you_name_at_gmail_com"
    assert auth.token_path("you@x.com").name == "gdrive.you_at_x_com.token"
    assert auth.SCOPES == ["https://www.googleapis.com/auth/drive.readonly"]


def test_oauth_client_is_shared_with_gmail():
    from ghostbrain.connectors.gdrive import auth
    from ghostbrain.connectors.gmail import auth as gmail_auth

    assert auth.oauth_client_path() == gmail_auth.oauth_client_path()


def test_load_credentials_without_token_raises():
    from ghostbrain.connectors.gdrive import auth

    with pytest.raises(auth.GdriveAuthError, match="No saved token"):
        auth.load_credentials("nobody@x.com")


def test_gdrive_is_an_account_connector():
    from ghostbrain import accounts

    assert "gdrive" in accounts.ACCOUNT_CONNECTORS
    assert accounts.SOURCE_TO_ACCOUNT_CONNECTOR["gdrive"] == "gdrive"
    assert accounts.account_connector_for_event({"source": "gdrive"}) == "gdrive"
```

`ghostbrain/api/tests/test_gdrive_wiring.py`:

```python
from __future__ import annotations

from pathlib import Path


def test_google_provider_resolves_gdrive_module():
    from ghostbrain.api.auth.providers.google_oauth import _mod
    from ghostbrain.connectors.gdrive import auth

    assert _mod("gdrive") is auth


def test_gdrive_registered_on_google_provider():
    from ghostbrain.api.auth import registry
    import ghostbrain.api.auth.providers.register_all  # noqa: F401

    assert registry.get("gdrive").pattern == "google_oauth"


def test_poll_registers_gdrive_account(monkeypatch, tmp_vault, tmp_state_dir):
    from ghostbrain import accounts
    from ghostbrain.api.auth.providers.google_oauth import GoogleProvider
    from ghostbrain.connectors.gdrive import auth

    monkeypatch.setattr(auth, "run_oauth_flow", lambda email: Path("/dev/null"))

    class S:
        _google_account = "me@x.com"
        status = error = account = next = None

    s = S()
    GoogleProvider().poll("gdrive", s)
    assert s.status == "success"
    assert accounts.get_account("gdrive", "me@x.com") is not None


def test_disconnect_removes_gdrive_token(tmp_state_dir):
    from ghostbrain.api.auth.disconnect import disconnect
    from ghostbrain.connectors.gdrive.auth import token_path

    p = token_path("me@x.com")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    disconnect("gdrive", "me@x.com")
    assert not p.exists()


def test_probe_sees_gdrive_token(tmp_state_dir):
    from ghostbrain.api.repo.connector_probe import probe
    from ghostbrain.connectors.gdrive.auth import token_path

    assert probe("gdrive").state == "off"
    p = token_path("me@x.com")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    assert probe("gdrive").state == "on"


def test_gdrive_listed_in_connectors(client, auth_headers):
    rows = {c["id"]: c for c in client.get("/v1/connectors", headers=auth_headers).json()}
    assert rows["gdrive"]["displayName"] == "Google Drive"
```

Before writing `test_gdrive_registered_on_google_provider`, open `ghostbrain/api/auth/registry.py` and use its real lookup function name (it may be `get`, `provider_for`, or a dict); adjust the one assert line to it.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gdrive_auth.py ghostbrain/api/tests/test_gdrive_wiring.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostbrain.connectors.gdrive'`.

- [ ] **Step 3: Implement**

`ghostbrain/connectors/gdrive/auth.py`:

```python
"""Google Drive OAuth helpers.

Reuses the shared ``google_oauth_client.json`` Desktop OAuth client that Gmail
and Calendar use; ``drive.readonly`` also authorises read calls to the Docs and
Sheets APIs. Tokens live at ``<state>/gdrive.<slug>.token`` per account.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("ghostbrain.connectors.gdrive.auth")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class GdriveAuthError(RuntimeError):
    """Drive credentials are missing, expired beyond refresh, or rejected."""


def state_dir() -> Path:
    raw = os.environ.get("GHOSTBRAIN_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".ghostbrain" / "state").resolve()


def slug(account_email: str) -> str:
    return account_email.lower().replace("@", "_at_").replace(".", "_")


def oauth_client_path() -> Path:
    return state_dir() / "google_oauth_client.json"


def token_path(account_email: str) -> Path:
    return state_dir() / f"gdrive.{slug(account_email)}.token"


def load_credentials(account_email: str):
    """Return refreshed Google ``Credentials``; raises ``GdriveAuthError``."""
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    tpath = token_path(account_email)
    if not tpath.exists():
        raise GdriveAuthError(
            f"No saved token for {account_email}. Connect Google Drive in the app."
        )
    creds = Credentials.from_authorized_user_file(str(tpath), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as e:
                raise GdriveAuthError(
                    f"Refresh token rejected for {account_email}: {e}. Reauthorize."
                ) from e
            tpath.write_text(creds.to_json(), encoding="utf-8")
            tpath.chmod(0o600)
        else:
            raise GdriveAuthError(
                f"Credentials invalid for {account_email} and no refresh token. Reauthorize."
            )
    return creds


def run_oauth_flow(account_email: str) -> Path:
    """Browser consent for the Drive read scope; saves and returns the token path."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_path = oauth_client_path()
    if not client_path.exists():
        raise GdriveAuthError(
            f"OAuth client config not found at {client_path}. Create a Desktop OAuth "
            "client at https://console.cloud.google.com/apis/credentials."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    creds = flow.run_local_server(
        port=0, open_browser=True, login_hint=account_email,
        prompt="consent", access_type="offline",
    )
    tpath = token_path(account_email)
    tpath.parent.mkdir(parents=True, exist_ok=True)
    tpath.write_text(creds.to_json(), encoding="utf-8")
    tpath.chmod(0o600)
    return tpath
```

`ghostbrain/connectors/gdrive/__init__.py`: a one-line module docstring `"""Google Drive connector — see docs/superpowers/specs/2026-09-28-gdrive-connector-design.md."""` (Task 6 adds the `GdriveConnector` export).

`ghostbrain/accounts.py`: append `"gdrive"` to the `ACCOUNT_CONNECTORS` tuple and add `"gdrive": "gdrive",` to `SOURCE_TO_ACCOUNT_CONNECTOR`.

`ghostbrain/api/auth/providers/google_oauth.py`: in `_mod`, before the calendar fallback:

```python
    if connector_id == "gdrive":
        from ghostbrain.connectors.gdrive import auth as m
        return m
```

and in `poll`, replace the `ensure_account(...)` line with:

```python
        acct_connector = {"gmail": "gmail", "gdrive": "gdrive"}.get(connector_id, "calendar_google")
        accounts.ensure_account(acct_connector, account)
```

Update the module docstring's first line to "Google OAuth provider for Gmail, Calendar and Drive connectors."

`register_all.py`: add `registry.register("gdrive", _google)` after the calendar line.

`disconnect.py`: add a branch after the gmail one:

```python
    elif connector_id == "gdrive" and account:
        from ghostbrain.connectors.gdrive.auth import token_path
        _rm(token_path(account))
```

`connector_probe.py` `probe()`: add `if connector_id == "gdrive": return _google_probe("gdrive")` next to the gmail case.

`api/repo/connectors.py` `_DISPLAY`: add

```python
    "gdrive": {
        "displayName": "Google Drive",
        "scopes": ["drive.readonly"],
        "pulls": ["Docs", "Sheets", "PDF / Word / Excel files you own or edited"],
        "vaultDestination": "20-contexts/{ctx}/gdrive/",
    },
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_gdrive_auth.py ghostbrain/api/tests/test_gdrive_wiring.py ghostbrain/api/tests/test_connectors.py ghostbrain/api/tests/test_auth.py tests/test_accounts.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector && git add ghostbrain/connectors/gdrive ghostbrain/accounts.py ghostbrain/api tests/test_gdrive_auth.py && git commit -m "feat(gdrive): auth module + account/connector registration

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Drive client helpers + test fakes

**Files:**
- Create: `ghostbrain/connectors/gdrive/drive.py`, `tests/gdrive_fakes.py`
- Test: `tests/test_gdrive_drive.py`

**Interfaces:**
- Consumes: `auth.load_credentials`, `auth.GdriveAuthError` (Task 1).
- Produces (module `ghostbrain.connectors.gdrive.drive`):
  - constants `GDOC`, `GSHEET`, `PDF`, `DOCX`, `XLSX`, `SUPPORTED_MIMES: tuple[str, ...]`, `FILE_FIELDS: str`, `MAX_RETRIES = 3`
  - `class DriveRateLimited(RuntimeError)`, `class DriveApiDisabled(RuntimeError)` (message = the Global Constraints API-not-enabled text)
  - `@dataclass Services(drive, docs, sheets)`; `build_services(email: str) -> Services`
  - `build_query(after: datetime, before: datetime | None = None) -> str`
  - `list_page(drive, *, after, before=None, page_token=None, page_size=100, fields=FILE_FIELDS) -> tuple[list[dict], str | None]`
  - `is_mine(file: dict) -> bool`; `parse_time(value: str) -> datetime`
  - `reasons(e: HttpError) -> set[str]`; `execute(request, *, api: str = "Drive")`
  - `folder_path(drive, file: dict, cache: dict) -> str | None`
  - `download(drive, file_id: str, dest: Path) -> None`
  - module attribute `_sleep = time.sleep` (patched in tests)
- Produces (`tests/gdrive_fakes.py`): `FakeDrive`, `FakeDocs`, `FakeSheets`, `fake_services(...) -> Services`, `http_error(status: int, reason: str) -> HttpError`, `drive_file(...) -> dict`, `install_fake_download(monkeypatch, drive: FakeDrive)`.

- [ ] **Step 1: Write the fakes** (test support, no test of their own)

`tests/gdrive_fakes.py`:

```python
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
```

- [ ] **Step 2: Write the failing tests**

`tests/test_gdrive_drive.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from googleapiclient.errors import HttpError

from ghostbrain.connectors.gdrive import drive
from ghostbrain.connectors.gdrive.auth import GdriveAuthError
from tests.gdrive_fakes import FakeDrive, drive_file, http_error

UTC = timezone.utc


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(drive, "_sleep", lambda s: None)


def test_build_query_window_and_mimes():
    q = drive.build_query(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC))
    assert q.startswith("trashed = false and (")
    for m in drive.SUPPORTED_MIMES:
        assert f"mimeType = '{m}'" in q
    assert "modifiedTime > '2026-09-01T00:00:00'" in q
    assert "modifiedTime < '2026-10-01T00:00:00'" in q
    assert "modifiedTime <" not in drive.build_query(datetime(2026, 9, 1, tzinfo=UTC))


def test_list_page_pages_and_passes_params():
    fake = FakeDrive([drive_file(str(i), modified=f"2026-09-0{i}T10:00:00.000Z") for i in range(1, 4)])
    files, token = drive.list_page(fake, after=datetime(2026, 1, 1, tzinfo=UTC), page_size=2)
    assert [f["id"] for f in files] == ["3", "2"] and token == "2"
    files, token = drive.list_page(fake, after=datetime(2026, 1, 1, tzinfo=UTC), page_size=2, page_token=token)
    assert [f["id"] for f in files] == ["1"] and token is None
    kw = fake.list_calls[0]
    assert kw["supportsAllDrives"] and kw["includeItemsFromAllDrives"]
    assert kw["orderBy"] == "modifiedTime desc"
    assert kw["fields"] == f"nextPageToken,files({drive.FILE_FIELDS})"


@pytest.mark.parametrize("owned,mod,expected", [
    (True, False, True), (False, True, True), (False, False, False),
])
def test_is_mine(owned, mod, expected):
    assert drive.is_mine(drive_file("x", owned=owned, modified_by_me=mod)) is expected


def test_execute_retries_rate_limit_then_succeeds():
    fake = FakeDrive([drive_file("a")])
    fake.fail_next = [http_error(403, "userRateLimitExceeded"), http_error(503, "backendError")]
    files, _ = drive.list_page(fake, after=datetime(2026, 1, 1, tzinfo=UTC))
    assert [f["id"] for f in files] == ["a"]


def test_execute_gives_up_after_retries():
    fake = FakeDrive([drive_file("a")])
    fake.fail_next = [http_error(429, "rateLimitExceeded")] * (drive.MAX_RETRIES + 1)
    with pytest.raises(drive.DriveRateLimited):
        drive.list_page(fake, after=datetime(2026, 1, 1, tzinfo=UTC))


def test_execute_maps_api_disabled():
    fake = FakeDrive()
    fake.fail_next = [http_error(403, "accessNotConfigured")]
    with pytest.raises(drive.DriveApiDisabled, match="Enable the Google Sheets API"):
        drive.execute(fake.list(q=""), api="Sheets")


def test_execute_maps_401_to_auth_error():
    fake = FakeDrive()
    fake.fail_next = [http_error(401, "authError")]
    with pytest.raises(GdriveAuthError):
        drive.execute(fake.list(q=""))


def test_execute_reraises_other_http_errors():
    fake = FakeDrive()
    fake.fail_next = [http_error(404, "notFound")]
    with pytest.raises(HttpError):
        drive.execute(fake.list(q=""))


def test_folder_path_walks_parents_and_skips_root():
    fake = FakeDrive()
    fake.folders = {
        "p2": {"id": "p2", "name": "Specs", "parents": ["p1"]},
        "p1": {"id": "p1", "name": "Work", "parents": ["root"]},
        "root": {"id": "root", "name": "My Drive"},
    }
    cache: dict = {}
    assert drive.folder_path(fake, drive_file("f", parents=["p2"]), cache) == "Work/Specs"
    assert set(cache) == {"p2", "p1", "root"}
    assert drive.folder_path(fake, drive_file("g"), cache) is None


def test_folder_path_is_best_effort():
    fake = FakeDrive()
    fake.fail_next = [http_error(404, "notFound")]
    assert drive.folder_path(fake, drive_file("f", parents=["gone"]), {}) is None


def test_parse_time_handles_z_and_millis():
    assert drive.parse_time("2026-09-01T10:00:00.123Z") == datetime(2026, 9, 1, 10, 0, 0, 123000, tzinfo=UTC)
```

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gdrive_drive.py -q -p no:cacheprovider`
Expected: FAIL — `ImportError` for `drive` (the fakes import it too).

- [ ] **Step 4: Implement `drive.py`**

```python
"""Thin helpers over the Drive v3 / Docs v1 / Sheets v4 discovery clients:
building services, the modifiedTime-windowed query, paging, error mapping
(rate limits → retry, API disabled → clear message, 401 → re-auth), folder
paths and streaming downloads."""
from __future__ import annotations

import dataclasses
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.errors import HttpError

from ghostbrain.api.repo.attachment_extract import DOCX_MIME, XLSX_MIME
from ghostbrain.connectors.gdrive.auth import GdriveAuthError, load_credentials

log = logging.getLogger("ghostbrain.connectors.gdrive.drive")

GDOC = "application/vnd.google-apps.document"
GSHEET = "application/vnd.google-apps.spreadsheet"
PDF = "application/pdf"
DOCX = DOCX_MIME
XLSX = XLSX_MIME
SUPPORTED_MIMES: tuple[str, ...] = (GDOC, GSHEET, PDF, DOCX, XLSX)

FILE_FIELDS = (
    "id,name,mimeType,modifiedTime,size,ownedByMe,modifiedByMe,"
    "owners(emailAddress,displayName),webViewLink,parents,"
    "lastModifyingUser(emailAddress,displayName)"
)

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0
_RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}
_DISABLED_REASONS = {"accessNotConfigured", "SERVICE_DISABLED"}

_sleep = time.sleep


class DriveRateLimited(RuntimeError):
    """Google kept rate-limiting after MAX_RETRIES backoffs."""


class DriveApiDisabled(RuntimeError):
    """The Drive/Docs/Sheets API isn't enabled for the OAuth client's project."""

    def __init__(self, api: str) -> None:
        super().__init__(
            f"Enable the Google {api} API in Google Cloud for your OAuth client's "
            "project (APIs & Services → Library)."
        )
        self.api = api


@dataclasses.dataclass
class Services:
    drive: object
    docs: object
    sheets: object


def build_services(email: str) -> Services:
    from googleapiclient.discovery import build

    creds = load_credentials(email)
    return Services(
        drive=build("drive", "v3", credentials=creds, cache_discovery=False),
        docs=build("docs", "v1", credentials=creds, cache_discovery=False),
        sheets=build("sheets", "v4", credentials=creds, cache_discovery=False),
    )


def parse_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def build_query(after: datetime, before: datetime | None = None) -> str:
    mimes = " or ".join(f"mimeType = '{m}'" for m in SUPPORTED_MIMES)
    q = f"trashed = false and ({mimes}) and modifiedTime > '{_rfc3339(after)}'"
    if before is not None:
        q += f" and modifiedTime < '{_rfc3339(before)}'"
    return q


def list_page(drive, *, after: datetime, before: datetime | None = None,
              page_token: str | None = None, page_size: int = 100,
              fields: str = FILE_FIELDS) -> tuple[list[dict], str | None]:
    req = drive.files().list(
        q=build_query(after, before),
        fields=f"nextPageToken,files({fields})",
        pageSize=page_size,
        pageToken=page_token,
        orderBy="modifiedTime desc",
        spaces="drive",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    )
    resp = execute(req)
    return list(resp.get("files") or []), resp.get("nextPageToken")


def is_mine(file: dict) -> bool:
    return bool(file.get("ownedByMe") or file.get("modifiedByMe"))


def reasons(e: HttpError) -> set[str]:
    try:
        err = json.loads(e.content.decode("utf-8")).get("error") or {}
    except (ValueError, AttributeError):
        return set()
    out = {x.get("reason") for x in err.get("errors") or []}
    out |= {x.get("reason") for x in err.get("details") or []}
    if err.get("status"):
        out.add(err["status"])
    return {r for r in out if r}


def execute(request, *, api: str = "Drive"):
    for attempt in range(MAX_RETRIES + 1):
        try:
            return request.execute()
        except HttpError as e:
            status = e.resp.status
            why = reasons(e)
            if why & _DISABLED_REASONS:
                raise DriveApiDisabled(api) from e
            if status == 401:
                raise GdriveAuthError(f"Google rejected the Drive token ({api} API). Reauthorize.") from e
            retryable = status == 429 or status >= 500 or (status == 403 and bool(why & _RATE_REASONS))
            if not retryable:
                raise
            if attempt == MAX_RETRIES:
                raise DriveRateLimited(f"{api} API still rate-limited after {MAX_RETRIES} retries") from e
            _sleep(BACKOFF_BASE_SECONDS * (2 ** attempt))
    raise AssertionError("unreachable")


def folder_path(drive, file: dict, cache: dict) -> str | None:
    """'A/B/C' for the file's first parent chain, excluding the Drive root.
    Best-effort: any failure returns None."""
    parents = file.get("parents") or []
    if not parents:
        return None
    names: list[str] = []
    pid = parents[0]
    try:
        for _ in range(20):
            if pid not in cache:
                cache[pid] = execute(drive.files().get(
                    fileId=pid, fields="id,name,parents", supportsAllDrives=True))
            node = cache[pid]
            up = node.get("parents") or []
            if not up:
                break
            names.append(node["name"])
            pid = up[0]
    except GdriveAuthError:
        raise
    except Exception:  # noqa: BLE001 — folder names are decoration
        log.debug("folder lookup failed for %s", file.get("id"), exc_info=True)
        return None
    return "/".join(reversed(names)) or None


def download(drive, file_id: str, dest: Path) -> None:
    """Stream a binary file to ``dest`` in 8 MB chunks (never fully in memory)."""
    from googleapiclient.http import MediaIoBaseDownload

    request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    with dest.open("wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk(num_retries=MAX_RETRIES)
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_gdrive_drive.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector && git add ghostbrain/connectors/gdrive/drive.py tests/gdrive_fakes.py tests/test_gdrive_drive.py && git commit -m "feat(gdrive): drive query, paging, error mapping + test fakes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Table rendering + path-based extraction

**Files:**
- Create: `ghostbrain/connectors/gdrive/tables.py`
- Modify: `ghostbrain/api/repo/attachment_extract.py:31-90`
- Test: `tests/test_gdrive_tables.py`, `ghostbrain/api/tests/test_attachment_extract.py` (append)

**Interfaces:**
- Produces: `tables.MAX_ROWS = 5000`, `tables.MAX_COLS = 50`, `tables.MAX_COLS_A1 = "AX"`, `tables.MAX_TABS = 50`, `@dataclass tables.Tab(name: str, rows: list[list], more_rows: bool = False, more_cols: bool = False)`, `tables.markdown_table(rows: list[list]) -> str` (no heading; `""` when empty), `tables.render_tab(tab: Tab) -> tuple[str, bool]`, `tables.render_tables(tabs: list[Tab], *, extra_tabs: int = 0) -> tuple[str, bool]`. `attachment_extract.extract_text(filename, mime, content: bytes | Path) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_gdrive_tables.py`:

```python
from __future__ import annotations

from ghostbrain.connectors.gdrive import tables
from ghostbrain.connectors.gdrive.tables import Tab


def test_markdown_table_header_escaping_and_trim():
    out = tables.markdown_table([
        ["Name", "Note", None, ""],
        ["a|b", "line1\nline2", None, ""],
        [3, 4.5, None, None],
        [None, "", None, None],
    ])
    assert out.splitlines() == [
        "| Name | Note |",
        "| --- | --- |",
        "| a\\|b | line1<br>line2 |",
        "| 3 | 4.5 |",
    ]


def test_markdown_table_pads_ragged_rows():
    assert tables.markdown_table([["a", "b", "c"], ["x"]]).splitlines()[-1] == "| x |  |  |"


def test_markdown_table_empty():
    assert tables.markdown_table([[None, ""], []]) == ""


def test_render_tab_row_and_col_caps():
    rows = [[f"c{j}" for j in range(tables.MAX_COLS + 3)] for _ in range(tables.MAX_ROWS + 10)]
    text, cut = tables.render_tab(Tab("Big", rows))
    lines = text.splitlines()
    assert lines[0] == "## Big"
    assert cut is True
    assert "_…truncated at 5,000 rows_" in lines
    assert "_…truncated at 50 columns_" in lines
    assert lines[2].count(" | ") == tables.MAX_COLS - 1
    assert sum(1 for line in lines if line.startswith("| c0 ")) == tables.MAX_ROWS


def test_render_tab_flags_from_caller():
    text, cut = tables.render_tab(Tab("T", [["a"]], more_rows=True))
    assert cut and text.endswith("_…truncated at 5,000 rows_")


def test_render_tables_skips_empty_and_caps_tabs():
    tabs = [Tab("Empty", [])] + [Tab(f"T{i}", [["v"]]) for i in range(tables.MAX_TABS + 2)]
    text, cut = tables.render_tables(tabs, extra_tabs=3)
    assert "## Empty" not in text
    assert text.count("\n## ") + text.startswith("## ") == tables.MAX_TABS
    assert text.endswith("_…5 more tabs_")
    assert cut


def test_max_cols_a1_matches_max_cols():
    n = 0
    for ch in tables.MAX_COLS_A1:
        n = n * 26 + (ord(ch) - 64)
    assert n == tables.MAX_COLS
```

Append to `ghostbrain/api/tests/test_attachment_extract.py`:

```python
def test_extract_text_accepts_a_path(tmp_path):
    p = tmp_path / "a.docx"
    p.write_bytes(_docx_bytes("From a path"))
    assert "From a path" in ex.extract_text("a.docx", ex.DOCX_MIME, p)
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(MINIMAL_PDF)
    assert "Hello PDF world" in ex.extract_text("a.pdf", "application/pdf", pdf)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gdrive_tables.py ghostbrain/api/tests/test_attachment_extract.py -q -p no:cacheprovider`
Expected: FAIL — `tables` import error; the path test fails inside `io.BytesIO(Path)` (`TypeError`).

- [ ] **Step 3: Implement `tables.py`**

```python
"""Rows of cell values → Markdown tables, with the size caps from the spec.
Shared by Google Sheets (Sheets API values), uploaded .xlsx (openpyxl) and
tables inside Google Docs (Docs API fallback)."""
from __future__ import annotations

import dataclasses

MAX_ROWS = 5000
MAX_COLS = 50
MAX_COLS_A1 = "AX"  # column letter of MAX_COLS
MAX_TABS = 50


@dataclasses.dataclass
class Tab:
    name: str
    rows: list[list]
    more_rows: bool = False
    more_cols: bool = False


def _cell(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\n", "<br>")
    return text.replace("|", "\\|")


def _trimmed(rows: list[list]) -> tuple[list[list[str]], int]:
    cells = [[_cell(v) for v in row] for row in rows]
    while cells and not any(c.strip() for c in cells[-1]):
        cells.pop()
    width = 0
    for row in cells:
        for i in range(len(row) - 1, -1, -1):
            if row[i].strip():
                width = max(width, i + 1)
                break
    return [(row + [""] * width)[:width] for row in cells], width


def markdown_table(rows: list[list]) -> str:
    cells, width = _trimmed(rows)
    if not cells or width == 0:
        return ""
    lines = [
        "| " + " | ".join(cells[0]) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in cells[1:]]
    return "\n".join(lines)


def render_tab(tab: Tab) -> tuple[str, bool]:
    more_rows = tab.more_rows or len(tab.rows) > MAX_ROWS
    kept = tab.rows[:MAX_ROWS]
    more_cols = tab.more_cols or any(len(r) > MAX_COLS for r in kept)
    table = markdown_table([list(r)[:MAX_COLS] for r in kept])
    if not table:
        return "", False
    parts = [f"## {tab.name}", "", table]
    notes = []
    if more_rows:
        notes.append(f"_…truncated at {MAX_ROWS:,} rows_")
    if more_cols:
        notes.append(f"_…truncated at {MAX_COLS} columns_")
    if notes:
        parts += [""] + notes
    return "\n".join(parts), bool(notes)


def render_tables(tabs: list[Tab], *, extra_tabs: int = 0) -> tuple[str, bool]:
    """Render up to MAX_TABS non-empty tabs. ``extra_tabs`` counts tabs the
    caller didn't even fetch (beyond MAX_TABS)."""
    parts: list[str] = []
    truncated = False
    extra = extra_tabs
    for tab in tabs:
        if len(parts) == MAX_TABS:
            extra += 1
            continue
        text, cut = render_tab(tab)
        if text:
            parts.append(text)
            truncated |= cut
    if extra:
        parts.append(f"_…{extra} more tabs_")
        truncated = True
    return "\n\n".join(parts), truncated
```

Note: the tabs test builds `MAX_TABS + 2` non-empty tabs plus `extra_tabs=3` → 2 overflow + 3 = `_…5 more tabs_`.

- [ ] **Step 4: Make `attachment_extract` accept a `Path`**

In `ghostbrain/api/repo/attachment_extract.py` change the signature to `def extract_text(filename: str, mime: str, content: bytes | Path) -> str:` and add a helper under `ExtractionError`:

```python
def _source(content: bytes | Path):
    """pypdf / python-docx / openpyxl all take a path or a binary stream; a
    path lets large Drive downloads stay on disk."""
    return str(content) if isinstance(content, Path) else io.BytesIO(content)
```

Replace `PdfReader(io.BytesIO(content))` → `PdfReader(_source(content))`, `docx.Document(io.BytesIO(content))` → `docx.Document(_source(content))`, `openpyxl.load_workbook(io.BytesIO(content), ...)` → `openpyxl.load_workbook(_source(content), ...)`, and the three `_extract_*` signatures to `content: bytes | Path`. Update the module docstring's first line to "Extract plain text from binary documents (PDF, .docx, .xlsx) given bytes or a file path."

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_gdrive_tables.py ghostbrain/api/tests/test_attachment_extract.py ghostbrain/api/tests/test_chat_attachments.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector && git add ghostbrain/connectors/gdrive/tables.py ghostbrain/api/repo/attachment_extract.py tests/test_gdrive_tables.py ghostbrain/api/tests/test_attachment_extract.py && git commit -m "feat(gdrive): markdown table renderer with caps; extractor accepts paths

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Conversion (Docs export + Docs API fallback, Sheets API, XLSX, PDF, DOCX)

**Files:**
- Create: `ghostbrain/connectors/gdrive/docs_json.py`, `ghostbrain/connectors/gdrive/convert.py`
- Test: `tests/test_gdrive_docs_json.py`, `tests/test_gdrive_convert.py`

**Interfaces:**
- Consumes: `drive.Services`, `drive.execute`, `drive.reasons`, `drive.download`, mime constants (Task 2); `tables.*` (Task 3); `attachment_extract.extract_text`, `ExtractionError` (Task 3).
- Produces: `docs_json.document_to_markdown(doc: dict) -> str`; `convert.MAX_DOWNLOAD_BYTES`, `convert.MAX_BODY_CHARS`, `convert.EMPTY_BODY`, `class convert.TooLarge(Exception)`, `@dataclass convert.ConvertResult(body: str, truncated: bool)`, `convert.cap_body(text: str) -> tuple[str, bool]`, `convert.convert(services: Services, file: dict) -> ConvertResult`.

- [ ] **Step 1: Write the failing tests**

`tests/test_gdrive_docs_json.py`:

```python
from __future__ import annotations

from ghostbrain.connectors.gdrive.docs_json import document_to_markdown


def _p(text, style="NORMAL_TEXT", bullet=None, link=None):
    run = {"textRun": {"content": text + "\n", "textStyle": {"link": {"url": link}} if link else {}}}
    para = {"elements": [run], "paragraphStyle": {"namedStyleType": style}}
    if bullet is not None:
        para["bullet"] = {"listId": "l1", "nestingLevel": bullet}
    return {"paragraph": para}


def test_headings_paragraphs_lists_links():
    doc = {"body": {"content": [
        {"sectionBreak": {}},
        _p("Plan", "TITLE"),
        _p("Scope", "HEADING_2"),
        _p("Plain text."),
        _p("one", bullet=0),
        _p("nested", bullet=1),
        _p("site", link="https://x.test"),
        _p(""),
    ]}}
    assert document_to_markdown(doc).split("\n\n") == [
        "# Plan", "## Scope", "Plain text.", "- one", "  - nested", "[site](https://x.test)",
    ]


def test_table_and_soft_line_breaks():
    cell = lambda t: {"content": [_p(t)]}  # noqa: E731
    doc = {"body": {"content": [
        _p("a\u000bb"),
        {"table": {"tableRows": [
            {"tableCells": [cell("H1"), cell("H2")]},
            {"tableCells": [cell("x"), cell("y|z")]},
        ]}},
    ]}}
    assert document_to_markdown(doc).split("\n\n") == [
        "a\nb", "| H1 | H2 |\n| --- | --- |\n| x | y\\|z |",
    ]
```

`tests/test_gdrive_convert.py`:

```python
from __future__ import annotations

import io

import pytest

from ghostbrain.connectors.gdrive import convert, drive, tables
from tests.gdrive_fakes import (
    FakeDocs, FakeDrive, FakeSheets, drive_file, fake_services, http_error, install_fake_download,
)


def _docx(*paras: str) -> bytes:
    from docx import Document
    d = Document()
    for p in paras:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _xlsx(sheets: dict[str, list[list]]) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_google_doc_uses_markdown_export():
    d = FakeDrive()
    d.exports["d1"] = b"# Title\n\nBody"
    res = convert.convert(fake_services(drive=d), drive_file("d1"))
    assert res.body == "# Title\n\nBody" and res.truncated is False


def test_big_google_doc_falls_back_to_docs_api():
    d = FakeDrive()
    d.too_big_exports.add("d1")
    docs = FakeDocs({"d1": {"body": {"content": [
        {"paragraph": {"elements": [{"textRun": {"content": "Huge doc\n"}}],
                       "paragraphStyle": {"namedStyleType": "HEADING_1"}}}]}}})
    res = convert.convert(fake_services(drive=d, docs=docs), drive_file("d1"))
    assert res.body == "# Huge doc"


def test_sheet_via_sheets_api_multi_tab():
    sh = FakeSheets({"s1": {"Budget": [["Item", "Cost"], ["Laptop", "1,200"]], "Empty": []}})
    res = convert.convert(fake_services(sheets=sh), drive_file("s1", mime=drive.GSHEET))
    assert res.body.startswith("## Budget\n\n| Item | Cost |")
    assert "Empty" not in res.body
    assert sh.batch_calls[0]["ranges"] == ["'Budget'!A1:AX5000", "'Empty'!A1:AX5000"]


def test_sheet_tab_names_are_quoted_in_ranges():
    sh = FakeSheets({"s1": {"Q3 'final'": [["a"]]}})
    convert.convert(fake_services(sheets=sh), drive_file("s1", mime=drive.GSHEET))
    assert sh.batch_calls[0]["ranges"] == ["'Q3 ''final'''!A1:AX5000"]


def test_sheet_truncation_from_grid_size():
    rows = [["v"] * tables.MAX_COLS for _ in range(tables.MAX_ROWS)]
    sh = FakeSheets({"s1": {"Log": rows}}, grid={"s1": {"Log": (9000, 80)}})
    res = convert.convert(fake_services(sheets=sh), drive_file("s1", mime=drive.GSHEET))
    assert res.truncated
    assert "_…truncated at 5,000 rows_" in res.body and "_…truncated at 50 columns_" in res.body


def test_sheet_tab_cap():
    sh = FakeSheets({"s1": {f"T{i}": [["v"]] for i in range(tables.MAX_TABS + 4)}})
    res = convert.convert(fake_services(sheets=sh), drive_file("s1", mime=drive.GSHEET))
    assert len(sh.batch_calls[0]["ranges"]) == tables.MAX_TABS
    assert res.body.endswith("_…4 more tabs_")


def test_xlsx_upload_formulas_become_values(monkeypatch, tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Calc"
    ws.append(["a", "b", "sum"])
    ws.append([1, 2, "=A2+B2"])
    p = tmp_path / "f.xlsx"
    wb.save(p)
    # openpyxl doesn't compute formulas; a saved-by-Excel file carries cached
    # values. Without a cache data_only gives None → the cell renders empty.
    d = FakeDrive()
    d.media["x1"] = p.read_bytes()
    install_fake_download(monkeypatch, d)
    res = convert.convert(fake_services(drive=d), drive_file("x1", mime=drive.XLSX, size=100))
    assert "## Calc" in res.body and "| 1 | 2 |" in res.body
    assert "=A2+B2" not in res.body


def test_xlsx_multi_tab(monkeypatch):
    d = FakeDrive()
    d.media["x1"] = _xlsx({"One": [["h"], ["r1"]], "Two": [["k"], ["r2"]]})
    install_fake_download(monkeypatch, d)
    res = convert.convert(fake_services(drive=d), drive_file("x1", mime=drive.XLSX, size=100))
    assert "## One" in res.body and "## Two" in res.body


def test_docx_upload(monkeypatch):
    d = FakeDrive()
    d.media["w1"] = _docx("Hello from Word")
    install_fake_download(monkeypatch, d)
    res = convert.convert(fake_services(drive=d), drive_file("w1", mime=drive.DOCX, size=100))
    assert "Hello from Word" in res.body


def test_empty_pdf_gets_placeholder(monkeypatch):
    d = FakeDrive()
    d.media["p1"] = b"%PDF-1.4 not really"
    install_fake_download(monkeypatch, d)
    res = convert.convert(fake_services(drive=d), drive_file("p1", mime=drive.PDF, size=100))
    assert res.body == convert.EMPTY_BODY


def test_too_large_skips_without_download(monkeypatch):
    called = []
    monkeypatch.setattr(drive, "download", lambda *a: called.append(a))
    with pytest.raises(convert.TooLarge):
        convert.convert(fake_services(), drive_file("p1", mime=drive.PDF, size=convert.MAX_DOWNLOAD_BYTES + 1))
    assert called == []


def test_cap_body_cuts_at_line_boundary():
    text = ("x" * 10 + "\n") * (convert.MAX_BODY_CHARS // 11 + 50)
    body, cut = convert.cap_body(text)
    assert cut and len(body) <= convert.MAX_BODY_CHARS + 60
    assert body.endswith("_…truncated (document continues in Drive)_")
    assert body.split("\n\n_…")[0].endswith("x" * 10)
    assert convert.cap_body("short") == ("short", False)


def test_other_http_errors_propagate():
    d = FakeDrive()
    d.fail_next = [http_error(404, "notFound")]
    from googleapiclient.errors import HttpError
    with pytest.raises(HttpError):
        convert.convert(fake_services(drive=d), drive_file("d1"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gdrive_docs_json.py tests/test_gdrive_convert.py -q -p no:cacheprovider`
Expected: FAIL — modules missing.

- [ ] **Step 3: Implement `docs_json.py`**

```python
"""Docs API ``documents.get`` JSON → Markdown. Only used for Google Docs
over Drive's 10 MB export limit; covers headings, paragraphs, bullet
nesting, links, soft line breaks and tables."""
from __future__ import annotations

from ghostbrain.connectors.gdrive.tables import markdown_table

_HEADINGS = {
    "TITLE": "#", "SUBTITLE": "##",
    "HEADING_1": "#", "HEADING_2": "##", "HEADING_3": "###",
    "HEADING_4": "####", "HEADING_5": "#####", "HEADING_6": "######",
}


def _runs(paragraph: dict) -> str:
    parts: list[str] = []
    for el in paragraph.get("elements") or []:
        run = el.get("textRun")
        if not run:
            continue
        text = (run.get("content") or "").replace("\n", "")
        if not text:
            continue
        url = (((run.get("textStyle") or {}).get("link")) or {}).get("url")
        parts.append(f"[{text}]({url})" if url else text)
    return "".join(parts).replace("\u000b", "\n").strip()


def _paragraph(paragraph: dict) -> str:
    text = _runs(paragraph)
    if not text:
        return ""
    style = (paragraph.get("paragraphStyle") or {}).get("namedStyleType", "NORMAL_TEXT")
    if style in _HEADINGS:
        return f"{_HEADINGS[style]} {text}"
    if "bullet" in paragraph:
        level = int(paragraph["bullet"].get("nestingLevel") or 0)
        return "  " * level + "- " + text
    return text


def _table(table: dict) -> str:
    rows = []
    for row in table.get("tableRows") or []:
        rows.append([
            " ".join(_runs(c["paragraph"]) for c in cell.get("content") or [] if "paragraph" in c)
            for cell in row.get("tableCells") or []
        ])
    return markdown_table(rows)


def document_to_markdown(doc: dict) -> str:
    blocks: list[str] = []
    for el in (doc.get("body") or {}).get("content") or []:
        if "paragraph" in el:
            blocks.append(_paragraph(el["paragraph"]))
        elif "table" in el:
            blocks.append(_table(el["table"]))
    return "\n\n".join(b for b in blocks if b)
```

- [ ] **Step 4: Implement `convert.py`**

```python
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
        fields="sheets.properties(title,gridProperties(rowCount,columnCount))",
    ), api="Sheets")
    props = [s["properties"] for s in meta.get("sheets") or []]
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

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
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
```

Note `_downloaded` returns whatever the reader returns — `(body, truncated)` for XLSX, `str` for PDF/DOCX — matching the two call sites in `convert`.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_gdrive_docs_json.py tests/test_gdrive_convert.py -q -p no:cacheprovider`
Expected: PASS. If `test_xlsx_upload_formulas_become_values` fails on the `"| 1 | 2 |"` assertion because of trailing-column formatting, print `res.body` and fix the assertion to the real row (`"| 1 | 2 |  |"`) — the point of the test is that the formula string never appears.

- [ ] **Step 6: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector && git add ghostbrain/connectors/gdrive/docs_json.py ghostbrain/connectors/gdrive/convert.py tests/test_gdrive_docs_json.py tests/test_gdrive_convert.py && git commit -m "feat(gdrive): convert Docs, Sheets, XLSX, PDF, DOCX to markdown

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Event shape, stable filenames, in-place store

**Files:**
- Create: `ghostbrain/connectors/gdrive/event.py`, `ghostbrain/connectors/gdrive/store.py`
- Modify: `ghostbrain/worker/note_generator.py:100-143`
- Test: `tests/test_gdrive_store.py`

**Interfaces:**
- Consumes: `convert.ConvertResult` (Task 4); mime constants (Task 2); `worker.pipeline.process_event`, `note_generator.write_note`, `note_generator._render`.
- Produces: `event.TYPE_BY_MIME: dict[str, str]`, `event.build_event(file: dict, *, account: str, result: ConvertResult, folder: str | None) -> dict`; `store.find_notes(file_id: str) -> list[Path]`, `store.upsert(event: dict) -> str` returning `"imported" | "updated" | "skipped"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_gdrive_store.py`:

```python
from __future__ import annotations

import yaml
import pytest

from ghostbrain.connectors.gdrive import event as ev_mod
from ghostbrain.connectors.gdrive import store
from ghostbrain.connectors.gdrive.convert import ConvertResult
from ghostbrain.paths import vault_path
from ghostbrain.worker import note_generator, pipeline
from ghostbrain.worker.router import RoutingDecision
from tests.gdrive_fakes import drive_file


@pytest.fixture
def fake_pipeline(monkeypatch):
    """process_event stand-in: routes everything to 'work' in live mode."""
    calls = []

    def _process(event):
        calls.append(event)
        note_generator.write_note(
            event, RoutingDecision("work", 0.95, "account", "account"),
            body=event["body"], write_to_context=True,
        )
        return {"context": "work"}

    monkeypatch.setattr(pipeline, "process_event", _process)
    return calls


def _event(fid="F1abc_-Z", name="Roadmap", modified="2026-09-01T10:00:00.000Z",
           body="v1", account="me@x.com"):
    f = drive_file(fid, name, modified=modified, parents=[])
    return ev_mod.build_event(f, account=account, result=ConvertResult(body, False), folder="Work/Plans")


def _front(p):
    text = p.read_text()
    return yaml.safe_load(text.split("---\n")[1]), text.split("---\n", 2)[2]


def test_build_event_shape():
    e = _event()
    assert e["id"] == "gdrive:F1abc_-Z" and e["source"] == "gdrive" and e["type"] == "doc"
    assert e["metadata"]["accountId"] == "me@x.com"
    assert e["metadata"]["driveModifiedTime"] == "2026-09-01T10:00:00.000Z"
    assert e["body"].startswith("# Roadmap\n\n[Open in Drive](https://docs.google.com/d/F1abc_-Z) · Work/Plans\n\nv1")


def test_new_file_goes_through_pipeline_with_stable_name(fake_pipeline):
    assert store.upsert(_event()) == "imported"
    paths = store.find_notes("F1abc_-Z")
    assert {p.name for p in paths} == {"roadmap-F1abc_-Z.md"}
    assert len(paths) == 2  # inbox + context twin
    front, _ = _front(paths[0])
    assert front["fileId"] == "F1abc_-Z" and front["folder"] == "Work/Plans"


def test_newer_version_rewrites_in_place_without_pipeline(fake_pipeline, monkeypatch):
    store.upsert(_event())
    fake_pipeline.clear()
    ctx_note = next(p for p in store.find_notes("F1abc_-Z") if "20-contexts" in p.parts)
    text = ctx_note.read_text().replace("routingMethod: account", "routingMethod: account\ntags:\n- keep")
    ctx_note.write_text(text)

    assert store.upsert(_event(modified="2026-09-02T09:00:00.000Z", body="v2")) == "updated"
    assert fake_pipeline == []
    for p in store.find_notes("F1abc_-Z"):
        front, body = _front(p)
        assert front["driveModifiedTime"] == "2026-09-02T09:00:00.000Z"
        assert front["context"] == "work"
        assert body.rstrip().endswith("v2")
    assert _front(ctx_note)[0]["tags"] == ["keep"]


def test_same_version_is_skipped(fake_pipeline):
    store.upsert(_event())
    assert store.upsert(_event()) == "skipped"
    assert store.upsert(_event(modified="2026-08-01T00:00:00.000Z")) == "skipped"


def test_upsert_updates_renamed_doc_under_old_filename(fake_pipeline):
    store.upsert(_event(name="Roadmap"))
    assert store.upsert(_event(name="Roadmap 2027", modified="2026-09-03T00:00:00.000Z", body="v3")) == "updated"
    paths = store.find_notes("F1abc_-Z")
    assert {p.name for p in paths} == {"roadmap-F1abc_-Z.md"}
    assert _front(paths[0])[0]["title"] == "Roadmap 2027"


def test_same_file_from_two_accounts_is_one_note(fake_pipeline):
    store.upsert(_event(account="me@x.com"))
    assert store.upsert(_event(account="me@work.com")) == "skipped"
    assert len(fake_pipeline) == 1


def test_moved_note_is_still_found(fake_pipeline):
    store.upsert(_event())
    ctx_note = next(p for p in store.find_notes("F1abc_-Z") if "20-contexts" in p.parts)
    dest = vault_path() / "20-contexts" / "personal" / "gdrive" / "archive" / ctx_note.name
    dest.parent.mkdir(parents=True)
    ctx_note.rename(dest)
    assert dest in store.find_notes("F1abc_-Z")


def test_other_sources_keep_timestamped_filenames():
    name = note_generator._filename_for(
        {"source": "gmail", "timestamp": "2026-09-01T10:00:00Z", "title": "Hi"}, "gmail:abc")
    assert name.startswith("20260901T100000-hi-")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gdrive_store.py -q -p no:cacheprovider`
Expected: FAIL — `event` / `store` modules missing.

- [ ] **Step 3: Modify `note_generator.py`**

In `_filename_for`, at the top of the function:

```python
    if event.get("source") == "gdrive":
        # One note per Drive file, updated in place: no timestamp, and the raw
        # file id (filesystem-safe, case-sensitive) is the lookup key.
        file_id = (event.get("metadata") or {}).get("fileId")
        if file_id:
            title_slug = _slugify(event.get("title") or "")[:60] or "doc"
            return f"{title_slug}-{file_id}.md"
```

In `_build_frontmatter`, add after the `slack` branch:

```python
    elif source == "gdrive":
        for key in ("fileId", "mimeType", "driveModifiedTime", "owners", "folder",
                    "accountId", "truncated"):
            if md.get(key) is not None:
                front[key] = md[key]
```

- [ ] **Step 4: Implement `event.py`**

```python
"""Drive file + converted body → the worker pipeline's event shape."""
from __future__ import annotations

from ghostbrain.connectors.gdrive import drive
from ghostbrain.connectors.gdrive.convert import ConvertResult

TYPE_BY_MIME = {
    drive.GDOC: "doc", drive.GSHEET: "sheet", drive.PDF: "pdf",
    drive.DOCX: "docx", drive.XLSX: "xlsx",
}


def build_event(file: dict, *, account: str, result: ConvertResult, folder: str | None) -> dict:
    url = file.get("webViewLink")
    links = " · ".join(x for x in (f"[Open in Drive]({url})" if url else "", folder or "") if x)
    body = f"# {file['name']}\n\n" + (f"{links}\n\n" if links else "") + result.body
    modifier = (file.get("lastModifyingUser") or {}).get("emailAddress") or "?"
    return {
        "id": f"gdrive:{file['id']}",
        "source": "gdrive",
        "type": TYPE_BY_MIME[file["mimeType"]],
        "subtype": "updated",
        "timestamp": file["modifiedTime"],
        "title": file["name"],
        "url": url,
        "actorId": f"gdrive:{modifier}",
        "body": body,
        "metadata": {
            "accountId": account,
            "fileId": file["id"],
            "mimeType": file["mimeType"],
            "driveModifiedTime": file["modifiedTime"],
            "owners": [o["emailAddress"] for o in file.get("owners") or [] if o.get("emailAddress")],
            "folder": folder,
            "truncated": result.truncated,
        },
    }
```

- [ ] **Step 5: Implement `store.py`**

```python
"""One vault note per Drive file. New files go through the normal worker
pipeline (routing); changed files are rewritten in place, keeping all
frontmatter the pipeline or the user set. The filename suffix ``-<fileId>.md``
is the lookup key, so there is no separate index."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

import yaml

from ghostbrain.connectors.gdrive.drive import parse_time
from ghostbrain.paths import vault_path
from ghostbrain.worker import note_generator, pipeline

log = logging.getLogger("ghostbrain.connectors.gdrive.store")

# Sync and backfill both run in the sidecar's scheduler threads; one lock
# makes "look up, then import or rewrite" atomic across them.
_lock = threading.Lock()


def find_notes(file_id: str) -> list[Path]:
    root = vault_path()
    pattern = f"*-{file_id}.md"
    found = sorted((root / "00-inbox" / "raw" / "gdrive").glob(pattern))
    contexts = root / "20-contexts"
    if contexts.exists():
        found += sorted(contexts.glob(f"*/gdrive/**/{pattern}"))
    return found


def _split(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    return yaml.safe_load(text[4:end]) or {}, text[end + 5:]


def _as_time(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return parse_time(value)
    return None


def _rewrite(path: Path, event: dict) -> None:
    front, _ = _split(path.read_text(encoding="utf-8"))
    md = event["metadata"]
    front["title"] = event["title"]
    front["updated"] = event["timestamp"]
    front["driveModifiedTime"] = md["driveModifiedTime"]
    front["truncated"] = md["truncated"]
    if md.get("folder"):
        front["folder"] = md["folder"]
    path.write_text(note_generator._render(front, event["body"]), encoding="utf-8")


def upsert(event: dict) -> str:
    md = event["metadata"]
    with _lock:
        paths = find_notes(md["fileId"])
        if not paths:
            pipeline.process_event(event)
            return "imported"
        stored = _as_time(_split(paths[0].read_text(encoding="utf-8"))[0].get("driveModifiedTime"))
        if stored is not None and stored >= parse_time(md["driveModifiedTime"]):
            return "skipped"
        for p in paths:
            _rewrite(p, event)
        return "updated"
```

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/test_gdrive_store.py tests/test_note_generator.py tests/test_pipeline.py -q -p no:cacheprovider` (drop any of the last two paths that don't exist — `ls tests | grep -E "note_gen|pipeline"` first).
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector && git add ghostbrain/connectors/gdrive/event.py ghostbrain/connectors/gdrive/store.py ghostbrain/worker/note_generator.py tests/test_gdrive_store.py && git commit -m "feat(gdrive): event shape, stable filenames, in-place note updates

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Ingest + hourly sync connector + scheduler job

**Files:**
- Create: `ghostbrain/connectors/gdrive/ingest.py`, `ghostbrain/connectors/gdrive/connector.py`, `ghostbrain/connectors/gdrive/runner.py`
- Modify: `ghostbrain/connectors/gdrive/__init__.py`, `ghostbrain/scheduler_jobs.py:16-26,216-229`, `ghostbrain/api/routes/connectors.py:18-21`
- Test: `tests/test_gdrive_connector.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: `ingest.OUTCOMES = ("imported", "updated", "skipped", "failed", "tooLarge")`; `ingest.ingest_file(services, account: str, file: dict, folders: dict) -> str` (one of OUTCOMES; re-raises `GdriveAuthError`, `DriveRateLimited`, `DriveApiDisabled`); `connector.GdriveConnector(config: {"accounts": list[str]}, queue_dir, state_dir, *, services_for=None, now=None)` with `.run() -> int`, `.health_check() -> bool`, `.stats: collections.Counter`; `connector.DEBOUNCE`, `connector.FIRST_RUN_LOOKBACK`; `connector.cursor_path() -> Path`; `runner.run() -> RunResult`. Scheduler job `gdrive` every 3600 s; `"gdrive"` in `SYNCABLE`.

- [ ] **Step 1: Write the failing tests**

`tests/test_gdrive_connector.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from ghostbrain import accounts_health
from ghostbrain.connectors.gdrive import connector as conn_mod
from ghostbrain.connectors.gdrive import drive, ingest, store
from ghostbrain.connectors.gdrive.auth import GdriveAuthError
from ghostbrain.connectors.gdrive.connector import GdriveConnector
from ghostbrain.paths import queue_dir, state_dir
from tests.gdrive_fakes import FakeDrive, drive_file, fake_services, http_error

UTC = timezone.utc
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(drive, "_sleep", lambda s: None)


@pytest.fixture
def upserts(monkeypatch):
    seen = []

    def _upsert(event):
        seen.append(event["metadata"]["fileId"])
        return "imported"

    monkeypatch.setattr(store, "upsert", _upsert)
    return seen


def make(accounts, services_by_account):
    def services_for(email):
        svc = services_by_account[email]
        if isinstance(svc, Exception):
            raise svc
        return svc
    return GdriveConnector({"accounts": accounts}, queue_dir(), state_dir(),
                           services_for=services_for, now=lambda: NOW)


def _docs_drive(files):
    d = FakeDrive(files)
    for f in files:
        d.exports[f["id"]] = b"body"
    return d


def test_first_run_looks_back_seven_days_and_filters_mine(upserts):
    d = _docs_drive([
        drive_file("recent", modified=iso(NOW - timedelta(days=2))),
        drive_file("shared", modified=iso(NOW - timedelta(days=2)), owned=False, modified_by_me=False),
        drive_file("old", modified=iso(NOW - timedelta(days=9))),
    ])
    c = make(["me@x.com"], {"me@x.com": fake_services(drive=d)})
    assert c.run() == 1
    assert upserts == ["recent"]
    assert "modifiedTime > '2026-09-21T12:00:00'" in d.list_calls[0]["q"]


def test_debounce_defers_recent_edits_and_holds_cursor(upserts):
    hot = NOW - timedelta(minutes=5)
    d = _docs_drive([
        drive_file("hot", modified=iso(hot)),
        drive_file("cold", modified=iso(NOW - timedelta(hours=2))),
    ])
    c = make(["me@x.com"], {"me@x.com": fake_services(drive=d)})
    c.run()
    assert upserts == ["cold"] and c.stats["deferred"] == 1
    cursor = json.loads(conn_mod.cursor_path().read_text())["me@x.com"]
    assert drive.parse_time(cursor) < hot


def test_cursor_advances_to_run_start_when_nothing_deferred(upserts):
    d = _docs_drive([drive_file("a", modified=iso(NOW - timedelta(hours=3)))])
    make(["me@x.com"], {"me@x.com": fake_services(drive=d)}).run()
    assert json.loads(conn_mod.cursor_path().read_text())["me@x.com"] == NOW.isoformat()
    assert (state_dir() / "gdrive.last_run").exists()


def test_failing_account_keeps_its_cursor(upserts):
    ok = _docs_drive([drive_file("a", modified=iso(NOW - timedelta(hours=3)))])
    limited = FakeDrive()
    limited.fail_next = [http_error(429, "rateLimitExceeded")] * (drive.MAX_RETRIES + 1)
    conn_mod.cursor_path().parent.mkdir(parents=True, exist_ok=True)
    old = (NOW - timedelta(days=1)).isoformat()
    conn_mod.cursor_path().write_text(json.dumps({"slow@x.com": old}))
    c = make(["me@x.com", "slow@x.com"],
             {"me@x.com": fake_services(drive=ok), "slow@x.com": fake_services(drive=limited)})
    c.run()
    cursors = json.loads(conn_mod.cursor_path().read_text())
    assert cursors["slow@x.com"] == old
    assert cursors["me@x.com"] == NOW.isoformat()
    assert accounts_health.health_for("gdrive", "slow@x.com")["status"] == accounts_health.STATUS_ERROR


def test_auth_failure_marks_account_auth_required(upserts):
    ok = _docs_drive([])
    c = make(["me@x.com", "bad@x.com"],
             {"me@x.com": fake_services(drive=ok), "bad@x.com": GdriveAuthError("revoked")})
    c.run()
    assert accounts_health.health_for("gdrive", "bad@x.com")["status"] == accounts_health.STATUS_AUTH


def test_all_accounts_failing_raises_and_saves_no_last_run(upserts):
    c = make(["bad@x.com"], {"bad@x.com": GdriveAuthError("revoked")})
    with pytest.raises(accounts_health.AllAccountsFailedError):
        c.run()
    assert not (state_dir() / "gdrive.last_run").exists()


def test_ingest_counts_failures_and_too_large(monkeypatch):
    d = FakeDrive()
    d.fail_next = [http_error(404, "notFound")]
    svc = fake_services(drive=d)
    assert ingest.ingest_file(svc, "me@x.com", drive_file("gone"), {}) == "failed"
    big = drive_file("big", mime=drive.PDF, size=10**12)
    assert ingest.ingest_file(svc, "me@x.com", big, {}) == "tooLarge"


def test_ingest_reraises_auth_and_rate_limits():
    d = FakeDrive()
    d.fail_next = [http_error(401, "authError")]
    with pytest.raises(GdriveAuthError):
        ingest.ingest_file(fake_services(drive=d), "me@x.com", drive_file("a"), {})


def test_runner_skips_without_accounts():
    from ghostbrain.connectors.gdrive import runner
    result = runner.run()
    assert result.ok and result.skipped_reason == "not configured"


def test_scheduler_registers_gdrive_hourly():
    from ghostbrain import scheduler_jobs
    from ghostbrain.api.routes.connectors import SYNCABLE

    class Rec:
        def __init__(self):
            self.jobs = {}

        def add_job(self, name, schedule, fn, label):
            self.jobs[name] = (schedule, label)

        def add_daemon(self, *a, **k):
            pass

    r = Rec()
    scheduler_jobs.register_connectors(r)
    assert r.jobs["gdrive"][0].seconds == 3600
    assert "gdrive" in SYNCABLE
```

If `register_connectors` calls other scheduler methods than `add_job`/`add_daemon`, add no-op methods to `Rec` for them (check `ghostbrain/scheduler_jobs.py` and `Interval`'s attribute name for the period — adjust `.seconds` if it differs).

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gdrive_connector.py -q -p no:cacheprovider`
Expected: FAIL — `ingest` / `connector` missing.

- [ ] **Step 3: Implement `ingest.py`**

```python
"""One Drive file → vault: convert, build the event, upsert. Shared by the
hourly sync and the backfill. Account-level failures (auth, rate limit, API
disabled) propagate; anything else about one file is counted as 'failed'."""
from __future__ import annotations

import logging

from ghostbrain.connectors.gdrive import convert, drive, store
from ghostbrain.connectors.gdrive.auth import GdriveAuthError
from ghostbrain.connectors.gdrive.event import build_event

log = logging.getLogger("ghostbrain.connectors.gdrive.ingest")

OUTCOMES = ("imported", "updated", "skipped", "failed", "tooLarge")
_ACCOUNT_LEVEL = (GdriveAuthError, drive.DriveRateLimited, drive.DriveApiDisabled)


def ingest_file(services: drive.Services, account: str, file: dict, folders: dict) -> str:
    try:
        result = convert.convert(services, file)
        folder = drive.folder_path(services.drive, file, folders)
        return store.upsert(build_event(file, account=account, result=result, folder=folder))
    except convert.TooLarge:
        log.info("gdrive: skipping %s (%s) — over the download cap", file.get("name"), file.get("id"))
        return "tooLarge"
    except _ACCOUNT_LEVEL:
        raise
    except Exception:  # noqa: BLE001 — one bad file never stops the run
        log.exception("gdrive: failed to ingest %s (%s)", file.get("name"), file.get("id"))
        return "failed"
```

- [ ] **Step 4: Implement `connector.py`**

```python
"""Hourly Google Drive sync. Per account: list files modified since that
account's cursor, keep the ones the user owns or edited, defer anything
edited in the last 30 minutes, ingest the rest. Cursors are per account so
one failing account never makes another skip a window."""
from __future__ import annotations

import collections
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ghostbrain.accounts_health import for_each_account
from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.gdrive import drive, ingest
from ghostbrain.connectors.gdrive.auth import GdriveAuthError, load_credentials
from ghostbrain.paths import state_dir

log = logging.getLogger("ghostbrain.connectors.gdrive")

DEBOUNCE = timedelta(minutes=30)
FIRST_RUN_LOOKBACK = timedelta(days=7)


def cursor_path() -> Path:
    return state_dir() / "gdrive_sync.json"


def _load_cursors() -> dict[str, str]:
    try:
        return json.loads(cursor_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_cursor(account: str, value: datetime) -> None:
    cursors = _load_cursors()
    cursors[account] = value.isoformat()
    cursor_path().parent.mkdir(parents=True, exist_ok=True)
    cursor_path().write_text(json.dumps(cursors, indent=2), encoding="utf-8")


class GdriveConnector(Connector):
    name = "gdrive"
    version = "1.0"

    def __init__(self, config: dict, queue_dir: Path, state_dir: Path, *,
                 services_for: Callable[[str], drive.Services] | None = None,
                 now: Callable[[], datetime] | None = None) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.accounts: list[str] = list(config.get("accounts") or [])
        self._services_for = services_for or drive.build_services
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.stats: collections.Counter = collections.Counter()

    def health_check(self) -> bool:
        for email in self.accounts:
            try:
                load_credentials(email)
                return True
            except GdriveAuthError:
                continue
        return False

    # run() is overridden: Drive notes are upserted directly (new → pipeline,
    # changed → in-place rewrite) instead of going through the event queue.
    def fetch(self, since: datetime) -> list[dict]:
        raise NotImplementedError("GdriveConnector.run() upserts directly")

    def normalize(self, raw: dict) -> dict:
        raise NotImplementedError("GdriveConnector.run() upserts directly")

    def run(self) -> int:
        started = self._now()
        for_each_account(
            "gdrive", self.accounts, lambda email: self._sync_account(email, started),
            account_id=lambda email: email, auth_errors=(GdriveAuthError,),
        )
        self._save_last_run()
        log.info("gdrive sync: %s", dict(self.stats))
        try:
            from ghostbrain.worker.audit import audit_log
            audit_log("gdrive_sync", None, **{k: int(v) for k, v in self.stats.items()})
        except Exception:  # noqa: BLE001
            log.debug("audit_log failed", exc_info=True)
        return self.stats["imported"] + self.stats["updated"]

    def _sync_account(self, email: str, started: datetime) -> list[dict]:
        services = self._services_for(email)
        stored = _load_cursors().get(email)
        since = drive.parse_time(stored) if stored else started - FIRST_RUN_LOOKBACK
        cutoff = started - DEBOUNCE
        oldest_deferred: datetime | None = None
        folders: dict = {}
        token: str | None = None
        while True:
            files, token = drive.list_page(services.drive, after=since, page_token=token)
            for f in files:
                if not drive.is_mine(f):
                    continue
                modified = drive.parse_time(f["modifiedTime"])
                if modified > cutoff:
                    self.stats["deferred"] += 1
                    oldest_deferred = min(oldest_deferred or modified, modified)
                    continue
                self.stats[ingest.ingest_file(services, email, f, folders)] += 1
            if not token:
                break
        cursor = started if oldest_deferred is None else min(started, oldest_deferred - timedelta(seconds=1))
        _save_cursor(email, cursor)
        return []
```

`ghostbrain/connectors/gdrive/__init__.py`:

```python
"""Google Drive connector — see docs/superpowers/specs/2026-09-28-gdrive-connector-design.md."""
from ghostbrain.connectors.gdrive.connector import GdriveConnector

__all__ = ["GdriveConnector"]
```

- [ ] **Step 5: Implement `runner.py` and wire the scheduler**

```python
"""In-process runner for the Google Drive connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain import accounts
from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.gdrive import GdriveConnector


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> GdriveConnector | None:
    accts = accounts.list_accounts("gdrive")
    if not accts:
        return None
    return GdriveConnector(config={"accounts": [a.id for a in accts]},
                           queue_dir=queue_dir, state_dir=state_dir)


def run() -> RunResult:
    return run_connector("gdrive", build=_build)
```

`scheduler_jobs.py`: import `from ghostbrain.connectors.gdrive import runner as gdrive_runner` with the other connector imports, and in `register_connectors` after the gmail line:

```python
    scheduler.add_job("gdrive", Interval(seconds=3600), gdrive_runner.run, "every 1h")
```

`api/routes/connectors.py`: add `"gdrive"` to `SYNCABLE`.

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/test_gdrive_connector.py tests/test_scheduler_jobs.py ghostbrain/api/tests/test_connectors.py -q -p no:cacheprovider` (skip `test_scheduler_jobs.py` if it doesn't exist).
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector && git add ghostbrain/connectors/gdrive ghostbrain/scheduler_jobs.py ghostbrain/api/routes/connectors.py tests/test_gdrive_connector.py && git commit -m "feat(gdrive): hourly sync with per-account cursors and edit debounce

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Resumable backfill job

**Files:**
- Create: `ghostbrain/connectors/gdrive/backfill.py`
- Modify: `ghostbrain/scheduler_jobs.py` (register `gdrive-backfill`)
- Test: `tests/test_gdrive_backfill.py`

**Interfaces:**
- Consumes: `drive.list_page`, `drive.is_mine`, `drive.build_services`, errors (Task 2); `ingest.ingest_file`, `ingest.OUTCOMES` (Task 6); `auth.slug` (Task 1); `accounts.list_accounts`.
- Produces (module `backfill`): `MAX_YEARS = 10`, `ESTIMATE_CAP = 5000`, `BATCH_SIZE = 25`; `_services_for` (module attr, patched in tests); `_today() -> date` (patched in tests); `state_path(account) -> Path`; `start(account: str, *, since: date) -> dict`; `get(account) -> dict | None`; `pause(account) -> dict | None`; `resume(account) -> dict | None`; `cancel(account) -> bool`; `estimate(account, *, since: date) -> dict` (`{"files": int, "capped": bool}`); `run_tick(*, batch_size: int = BATCH_SIZE) -> dict`. State dict keys: `account, status, since, cursor, pageToken, imported, updated, skipped, failed, tooLarge, error, startedAt, updatedAt` + (from `get`/`start`/`pause`/`resume`) `monthsTotal, monthsDone`.

- [ ] **Step 1: Write the failing tests**

`tests/test_gdrive_backfill.py`:

```python
from __future__ import annotations

import json
from datetime import date

import pytest

from ghostbrain import accounts
from ghostbrain.connectors.gdrive import backfill, drive, ingest
from ghostbrain.connectors.gdrive.auth import GdriveAuthError
from tests.gdrive_fakes import FakeDrive, drive_file, fake_services, http_error

TODAY = date(2026, 9, 28)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(backfill, "_today", lambda: TODAY)
    monkeypatch.setattr(drive, "_sleep", lambda s: None)
    accounts.ensure_account("gdrive", "me@x.com")


@pytest.fixture
def world(monkeypatch):
    """A FakeDrive per account + a recording ingest."""
    drives: dict[str, FakeDrive] = {"me@x.com": FakeDrive()}
    ingested: list[str] = []
    outcome = {"value": "imported"}

    def services_for(email):
        d = drives[email]
        if isinstance(d, Exception):
            raise d
        return fake_services(drive=d)

    def _ingest(services, account, f, folders):
        ingested.append(f["id"])
        return outcome["value"]

    monkeypatch.setattr(backfill, "_services_for", services_for)
    monkeypatch.setattr(ingest, "ingest_file", _ingest)
    return drives, ingested, outcome


def test_start_clamps_since_and_reports_progress():
    st = backfill.start("me@x.com", since=date(2001, 1, 1))
    assert st["status"] == "running" and st["cursor"] == "2026-09"
    assert date.fromisoformat(st["since"]) >= date(2016, 9, 28)
    assert st["monthsDone"] == 0 and st["monthsTotal"] > 100


def test_start_returns_existing_unfinished_backfill():
    a = backfill.start("me@x.com", since=date(2025, 9, 28))
    b = backfill.start("me@x.com", since=date(2020, 1, 1))
    assert b["since"] == a["since"]


def test_idle_tick():
    assert backfill.run_tick() == {"skipped": "idle"}


def test_walks_months_backwards_with_paging_then_done(world):
    drives, ingested, _ = world
    drives["me@x.com"].file_list = [
        drive_file("sep1", modified="2026-09-10T00:00:00.000Z"),
        drive_file("sep2", modified="2026-09-11T00:00:00.000Z"),
        drive_file("sep3", modified="2026-09-12T00:00:00.000Z"),
        drive_file("aug", modified="2026-08-15T00:00:00.000Z"),
        drive_file("shared", modified="2026-08-16T00:00:00.000Z", owned=False, modified_by_me=False),
    ]
    backfill.start("me@x.com", since=date(2026, 8, 1))
    backfill.run_tick(batch_size=2)
    st = backfill.get("me@x.com")
    assert st["cursor"] == "2026-09" and st["pageToken"] == "2"
    backfill.run_tick(batch_size=2)
    assert backfill.get("me@x.com")["cursor"] == "2026-08"
    backfill.run_tick(batch_size=2)
    st = backfill.get("me@x.com")
    assert st["status"] == "done" and st["monthsDone"] == st["monthsTotal"]
    assert ingested == ["sep3", "sep2", "sep1", "aug"]
    assert st["imported"] == 4


def test_month_boundary_file_is_included(world):
    drives, ingested, _ = world
    drives["me@x.com"].file_list = [drive_file("edge", modified="2026-08-01T00:00:00.000Z")]
    backfill.start("me@x.com", since=date(2026, 7, 1))
    for _ in range(4):
        backfill.run_tick()
    assert ingested.count("edge") == 1


def test_counts_outcomes(world):
    drives, _, outcome = world
    drives["me@x.com"].file_list = [drive_file("a", modified="2026-09-10T00:00:00.000Z")]
    outcome["value"] = "tooLarge"
    backfill.start("me@x.com", since=date(2026, 9, 1))
    backfill.run_tick()
    assert backfill.get("me@x.com")["tooLarge"] == 1


def test_resume_after_crash_reuses_page_token(world):
    drives, ingested, _ = world
    drives["me@x.com"].file_list = [drive_file(f"f{i}", modified=f"2026-09-1{i}T00:00:00.000Z") for i in range(3)]
    backfill.start("me@x.com", since=date(2026, 9, 1))
    p = backfill.state_path("me@x.com")
    st = json.loads(p.read_text())
    st["pageToken"] = "1"
    p.write_text(json.dumps(st))
    backfill.run_tick(batch_size=5)
    assert ingested == ["f1", "f0"]


def test_auth_error_then_resume(world):
    drives, _, _ = world
    drives["me@x.com"] = GdriveAuthError("revoked")
    backfill.start("me@x.com", since=date(2026, 9, 1))
    backfill.run_tick()
    st = backfill.get("me@x.com")
    assert st["status"] == "error" and st["error"] == "needs re-auth"
    assert backfill.run_tick() == {"skipped": "idle"}
    drives["me@x.com"] = FakeDrive()
    assert backfill.resume("me@x.com")["status"] == "running"
    assert backfill.get("me@x.com")["error"] is None


def test_api_disabled_sets_error_message(world):
    drives, _, _ = world
    drives["me@x.com"].fail_next = [http_error(403, "accessNotConfigured")]
    backfill.start("me@x.com", since=date(2026, 9, 1))
    backfill.run_tick()
    assert "Enable the Google Drive API" in backfill.get("me@x.com")["error"]


def test_rate_limit_leaves_state_unchanged(world):
    drives, _, _ = world
    backfill.start("me@x.com", since=date(2026, 9, 1))
    before = backfill.get("me@x.com")
    drives["me@x.com"].fail_next = [http_error(429, "rateLimitExceeded")] * (drive.MAX_RETRIES + 1)
    assert backfill.run_tick()["skipped"] == "rate_limited"
    after = backfill.get("me@x.com")
    assert (after["status"], after["cursor"], after["pageToken"]) == ("running", before["cursor"], before["pageToken"])


def test_pause_skips_and_cancel_deletes_state(world):
    backfill.start("me@x.com", since=date(2026, 9, 1))
    assert backfill.pause("me@x.com")["status"] == "paused"
    assert backfill.run_tick() == {"skipped": "idle"}
    assert backfill.cancel("me@x.com") is True
    assert backfill.get("me@x.com") is None


def test_disabled_account_is_skipped_removed_account_cancelled(world):
    backfill.start("me@x.com", since=date(2026, 9, 1))
    acc = accounts.get_account("gdrive", "me@x.com")
    import dataclasses
    accounts.upsert_account(dataclasses.replace(acc, enabled=False), check_context=False)
    assert backfill.run_tick() == {"skipped": "idle"}
    assert backfill.get("me@x.com") is not None
    accounts.remove_account("gdrive", "me@x.com")
    backfill.run_tick()
    assert backfill.get("me@x.com") is None


def test_round_robin_picks_least_recently_updated(world):
    drives, _, _ = world
    accounts.ensure_account("gdrive", "b@x.com")
    drives["b@x.com"] = FakeDrive()
    backfill.start("me@x.com", since=date(2026, 9, 1))
    backfill.start("b@x.com", since=date(2026, 9, 1))
    first = backfill.run_tick()["account"]
    second = backfill.run_tick()["account"]
    assert {first, second} == {"me@x.com", "b@x.com"}


def test_estimate_counts_mine_and_caps(world, monkeypatch):
    drives, _, _ = world
    drives["me@x.com"].file_list = [
        drive_file("a", modified="2026-09-01T00:00:00.000Z"),
        drive_file("s", modified="2026-09-01T00:00:00.000Z", owned=False, modified_by_me=False),
    ]
    assert backfill.estimate("me@x.com", since=date(2026, 1, 1)) == {"files": 1, "capped": False}
    monkeypatch.setattr(backfill, "ESTIMATE_CAP", 1)
    assert backfill.estimate("me@x.com", since=date(2026, 1, 1)) == {"files": 1, "capped": True}


def test_scheduler_registers_backfill_tick():
    from ghostbrain import scheduler_jobs

    class Rec:
        def __init__(self):
            self.jobs = {}

        def add_job(self, name, schedule, fn, label):
            self.jobs[name] = (schedule, label)

        def add_daemon(self, *a, **k):
            pass

    r = Rec()
    scheduler_jobs.register_connectors(r)
    assert r.jobs["gdrive-backfill"][0].seconds == 120
```

Check the real signatures of `accounts.ensure_account`, `accounts.upsert_account` and `accounts.remove_account` (`ghostbrain/accounts.py:137-205`) before running; adapt the three call sites in the test if their parameters differ.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_gdrive_backfill.py -q -p no:cacheprovider`
Expected: FAIL — `backfill` missing.

- [ ] **Step 3: Implement `backfill.py`**

```python
"""Resumable per-account Drive backfill, ticked by the in-app scheduler.

State lives in ``<state>/gdrive_backfill.<slug>.json``. The cursor is a month
(``YYYY-MM``) walking backwards from the current month; ``pageToken`` resumes
within the month. State is persisted after every file, and re-listing a page
after a crash is harmless because unchanged files upsert as 'skipped'."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from ghostbrain import accounts
from ghostbrain.connectors.gdrive import drive, ingest
from ghostbrain.connectors.gdrive.auth import GdriveAuthError, slug
from ghostbrain.paths import state_dir

log = logging.getLogger("ghostbrain.connectors.gdrive.backfill")

MAX_YEARS = 10
ESTIMATE_CAP = 5000
BATCH_SIZE = 25
_COUNTERS = ("imported", "updated", "skipped", "failed", "tooLarge")

_services_for = drive.build_services


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_path(account: str) -> Path:
    return state_dir() / f"gdrive_backfill.{slug(account)}.json"


def _load_path(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(st: dict) -> None:
    st["updatedAt"] = _now_iso()
    p = state_path(st["account"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2), encoding="utf-8")
    tmp.replace(p)


def _month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def _with_progress(st: dict) -> dict:
    today = _today()
    since = date.fromisoformat(st["since"])
    y, m = map(int, st["cursor"].split("-"))
    total = _month_index(today) - _month_index(since) + 1
    done = total if st["status"] == "done" else _month_index(today) - (y * 12 + m - 1)
    return {**st, "monthsTotal": total, "monthsDone": max(0, min(done, total))}


def start(account: str, *, since: date) -> dict:
    existing = _load_path(state_path(account))
    if existing and existing.get("status") != "done":
        return _with_progress(existing)
    today = _today()
    since = max(since, today - timedelta(days=365 * MAX_YEARS + MAX_YEARS // 4))
    st = {
        "account": account, "status": "running", "since": since.isoformat(),
        "cursor": today.strftime("%Y-%m"), "pageToken": None,
        **{k: 0 for k in _COUNTERS},
        "error": None, "startedAt": _now_iso(), "updatedAt": _now_iso(),
    }
    _save(st)
    return _with_progress(st)


def get(account: str) -> dict | None:
    st = _load_path(state_path(account))
    return _with_progress(st) if st else None


def _set_status(account: str, allowed: tuple[str, ...], status: str) -> dict | None:
    st = _load_path(state_path(account))
    if st is None:
        return None
    if st["status"] in allowed:
        st["status"] = status
        st["error"] = None if status == "running" else st.get("error")
        _save(st)
    return _with_progress(st)


def pause(account: str) -> dict | None:
    return _set_status(account, ("running",), "paused")


def resume(account: str) -> dict | None:
    return _set_status(account, ("paused", "error"), "running")


def cancel(account: str) -> bool:
    try:
        state_path(account).unlink()
        return True
    except FileNotFoundError:
        return False


def _utc_midnight(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def estimate(account: str, *, since: date) -> dict:
    services = _services_for(account)
    after = _utc_midnight(since) - timedelta(seconds=1)
    count, token = 0, None
    while True:
        files, token = drive.list_page(services.drive, after=after, page_token=token,
                                       page_size=1000, fields="id,ownedByMe,modifiedByMe")
        count += sum(1 for f in files if drive.is_mine(f))
        if count >= ESTIMATE_CAP:
            return {"files": ESTIMATE_CAP, "capped": True}
        if not token:
            return {"files": count, "capped": False}


def run_tick(*, batch_size: int = BATCH_SIZE) -> dict:
    registry = {a.id.lower(): a for a in accounts.list_accounts("gdrive", include_disabled=True)}
    runnable: list[dict] = []
    for path in sorted(state_dir().glob("gdrive_backfill.*.json")):
        st = _load_path(path)
        if st is None:
            continue
        acc = registry.get(str(st.get("account", "")).lower())
        if acc is None:
            path.unlink(missing_ok=True)  # account removed → backfill cancelled
            continue
        if acc.enabled and st.get("status") == "running":
            runnable.append(st)
    if not runnable:
        return {"skipped": "idle"}
    return _tick(min(runnable, key=lambda s: s.get("updatedAt") or ""), batch_size)


def _tick(st: dict, batch_size: int) -> dict:
    account = st["account"]
    since = _utc_midnight(date.fromisoformat(st["since"]))
    y, m = map(int, st["cursor"].split("-"))
    month_start = datetime(y, m, 1, tzinfo=timezone.utc)
    next_start = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
    # modifiedTime > after is strict: back off one second so a file at exactly
    # 00:00:00 on the 1st lands in this month's window.
    after = max(month_start, since) - timedelta(seconds=1)
    try:
        services = _services_for(account)
        files, token = drive.list_page(services.drive, after=after, before=next_start,
                                       page_token=st.get("pageToken"), page_size=batch_size)
        folders: dict = {}
        for f in files:
            if not drive.is_mine(f):
                continue
            st[ingest.ingest_file(services, account, f, folders)] += 1
            _save(st)
    except GdriveAuthError:
        st.update(status="error", error="needs re-auth")
        _save(st)
        return {"account": account, "status": "error"}
    except drive.DriveApiDisabled as e:
        st.update(status="error", error=str(e))
        _save(st)
        return {"account": account, "status": "error"}
    except drive.DriveRateLimited:
        log.warning("gdrive backfill for %s rate-limited; retrying next tick", account)
        return {"account": account, "skipped": "rate_limited"}

    if token:
        st["pageToken"] = token
    else:
        st["pageToken"] = None
        if month_start <= since:
            st["status"] = "done"
        else:
            prev = month_start - timedelta(days=1)
            st["cursor"] = prev.strftime("%Y-%m")
    _save(st)
    return {"account": account, "cursor": st["cursor"], "processed": len(files), "status": st["status"]}
```

- [ ] **Step 4: Register the tick**

In `scheduler_jobs.py`, import `from ghostbrain.connectors.gdrive import backfill as gdrive_backfill` and after the `gdrive` job:

```python
    scheduler.add_job(
        "gdrive-backfill",
        Interval(seconds=120),
        lambda: _wrap_job("gdrive-backfill", gdrive_backfill.run_tick),
        "every 2m",
    )
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_gdrive_backfill.py tests/test_gdrive_connector.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector && git add ghostbrain/connectors/gdrive/backfill.py ghostbrain/scheduler_jobs.py tests/test_gdrive_backfill.py && git commit -m "feat(gdrive): resumable month-by-month backfill job

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Backfill API routes

**Files:**
- Modify: `ghostbrain/api/routes/connectors.py` (append)
- Test: `ghostbrain/api/tests/test_gdrive_backfill_routes.py`

**Interfaces:**
- Consumes: `backfill.start/get/pause/resume/cancel/estimate` (Task 7); `accounts.get_account`.
- Produces: `GET/POST/DELETE /v1/connectors/gdrive/accounts/{account_id}/backfill`, `GET …/backfill/estimate?years=N`, `POST …/backfill/pause`, `POST …/backfill/resume`. POST body `{"years": int 1..10}`.

- [ ] **Step 1: Write the failing tests**

`ghostbrain/api/tests/test_gdrive_backfill_routes.py`:

```python
from __future__ import annotations

from datetime import date

import pytest

from ghostbrain import accounts
from ghostbrain.connectors.gdrive import backfill
from ghostbrain.connectors.gdrive.auth import GdriveAuthError

BASE = "/v1/connectors/gdrive/accounts/me@x.com/backfill"


@pytest.fixture(autouse=True)
def _acct(tmp_vault, tmp_state_dir, monkeypatch):
    monkeypatch.setattr(backfill, "_today", lambda: date(2026, 9, 28))
    accounts.ensure_account("gdrive", "me@x.com")


@pytest.fixture
def scheduler_on(client):
    client.app.state.scheduler = object()
    yield
    client.app.state.scheduler = None


def test_get_404_when_none(client, auth_headers):
    assert client.get(BASE, headers=auth_headers).status_code == 404


def test_unknown_account_404(client, auth_headers, scheduler_on):
    r = client.post("/v1/connectors/gdrive/accounts/who@x.com/backfill", json={"years": 1}, headers=auth_headers)
    assert r.status_code == 404


def test_start_requires_scheduler(client, auth_headers):
    client.app.state.scheduler = None
    r = client.post(BASE, json={"years": 3}, headers=auth_headers)
    assert r.status_code == 409 and "Scheduler" in r.json()["detail"]


def test_start_validates_years(client, auth_headers, scheduler_on):
    assert client.post(BASE, json={"years": 0}, headers=auth_headers).status_code == 422
    assert client.post(BASE, json={"years": 11}, headers=auth_headers).status_code == 422


def test_start_get_pause_resume_cancel(client, auth_headers, scheduler_on):
    r = client.post(BASE, json={"years": 3}, headers=auth_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "running" and body["since"] == "2023-09-29"
    assert client.get(BASE, headers=auth_headers).json()["monthsTotal"] == body["monthsTotal"]
    assert client.post(f"{BASE}/pause", headers=auth_headers).json()["status"] == "paused"
    assert client.post(f"{BASE}/resume", headers=auth_headers).json()["status"] == "running"
    assert client.delete(BASE, headers=auth_headers).json() == {"ok": True}
    assert client.post(f"{BASE}/pause", headers=auth_headers).status_code == 404


def test_estimate(client, auth_headers, monkeypatch):
    seen = {}

    def fake(account, *, since):
        seen["since"] = since
        return {"files": 42, "capped": False}

    monkeypatch.setattr(backfill, "estimate", fake)
    r = client.get(f"{BASE}/estimate?years=2", headers=auth_headers)
    assert r.json() == {"files": 42, "capped": False, "since": "2024-09-28"}


def test_estimate_auth_error_is_409(client, auth_headers, monkeypatch):
    def boom(account, *, since):
        raise GdriveAuthError("revoked")

    monkeypatch.setattr(backfill, "estimate", boom)
    r = client.get(f"{BASE}/estimate?years=1", headers=auth_headers)
    assert r.status_code == 409 and r.json()["detail"] == "needs re-auth"
```

`since` for N years = `today - timedelta(days=365 * N)`: 2026-09-28 − 1095 days = 2023-09-29 (Feb 2024 is a leap day); − 730 days = 2024-09-28.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_gdrive_backfill_routes.py -q -p no:cacheprovider`
Expected: FAIL — 404/405 for the new paths.

- [ ] **Step 3: Implement** (append to `ghostbrain/api/routes/connectors.py`; add `from datetime import timedelta` and `from pydantic import Field` to the imports)

```python
# --- Google Drive backfill -------------------------------------------------

class BackfillStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    years: int = Field(ge=1, le=10)


def _gdrive_account(account_id: str) -> str:
    from ghostbrain import accounts

    acc = accounts.get_account("gdrive", account_id)
    if acc is None:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")
    return acc.id


def _since_for(years: int):
    from ghostbrain.connectors.gdrive import backfill

    return backfill._today() - timedelta(days=365 * years)


@router.get("/gdrive/accounts/{account_id}/backfill")
def gdrive_backfill_get(account_id: str) -> dict:
    from ghostbrain.connectors.gdrive import backfill

    st = backfill.get(_gdrive_account(account_id))
    if st is None:
        raise HTTPException(status_code=404, detail="No backfill for this account")
    return st


@router.get("/gdrive/accounts/{account_id}/backfill/estimate")
def gdrive_backfill_estimate(account_id: str, years: int = 3) -> dict:
    from ghostbrain.connectors.gdrive import backfill, drive
    from ghostbrain.connectors.gdrive.auth import GdriveAuthError

    if not 1 <= years <= 10:
        raise HTTPException(status_code=422, detail="years must be 1-10")
    since = _since_for(years)
    try:
        result = backfill.estimate(_gdrive_account(account_id), since=since)
    except GdriveAuthError as e:
        raise HTTPException(status_code=409, detail="needs re-auth") from e
    except drive.DriveApiDisabled as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {**result, "since": since.isoformat()}


@router.post("/gdrive/accounts/{account_id}/backfill", status_code=201)
def gdrive_backfill_start(account_id: str, body: BackfillStart, request: Request) -> dict:
    from ghostbrain.connectors.gdrive import backfill

    account = _gdrive_account(account_id)
    if getattr(request.app.state, "scheduler", None) is None:
        raise HTTPException(
            status_code=409,
            detail="Scheduler not running. Enable 'Run scheduler in-app' in Settings.",
        )
    return backfill.start(account, since=_since_for(body.years))


@router.post("/gdrive/accounts/{account_id}/backfill/{action}")
def gdrive_backfill_action(account_id: str, action: str) -> dict:
    from ghostbrain.connectors.gdrive import backfill

    fn = {"pause": backfill.pause, "resume": backfill.resume}.get(action)
    if fn is None:
        raise HTTPException(status_code=404, detail=f"Unknown action: {action}")
    st = fn(_gdrive_account(account_id))
    if st is None:
        raise HTTPException(status_code=404, detail="No backfill for this account")
    return st


@router.delete("/gdrive/accounts/{account_id}/backfill")
def gdrive_backfill_cancel(account_id: str) -> dict:
    from ghostbrain.connectors.gdrive import backfill

    backfill.cancel(_gdrive_account(account_id))
    return {"ok": True}
```

If the `scheduler_on` fixture's `client.app.state.scheduler = object()` leaks into other endpoints during the app's lifespan, that's fine — the fixture resets it.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest ghostbrain/api/tests/test_gdrive_backfill_routes.py ghostbrain/api/tests/test_connectors.py ghostbrain/api/tests/test_connectors_accounts.py ghostbrain/api/tests/test_account_update_route.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector && git add ghostbrain/api/routes/connectors.py ghostbrain/api/tests/test_gdrive_backfill_routes.py && git commit -m "feat(gdrive): backfill API routes

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Desktop — catalog card, types, hooks, backfill UI

**Files:**
- Create: `desktop/src/renderer/components/AccountBackfill.tsx`, `desktop/src/renderer/__tests__/AccountBackfill.test.tsx`
- Modify: `desktop/src/shared/api-types.ts`, `desktop/src/renderer/lib/api/hooks.ts`, `desktop/src/renderer/lib/connector-catalog.ts`, `desktop/src/renderer/components/ConnectorAccounts.tsx`, `desktop/src/renderer/__tests__/connector-catalog.test.ts` (if it asserts the card list)

**Interfaces:**
- Consumes: Task 8 routes.
- Produces: types `BackfillStatus`, `BackfillState`, `BackfillEstimate`; hooks `useBackfill(connectorId, accountId)`, `useBackfillEstimate(connectorId, accountId, years, enabled)`, `useStartBackfill()`, `useBackfillAction()`; `BACKFILL_CONNECTORS: ReadonlySet<string>` and `<AccountBackfill connectorId accountId onReauth />`.

- [ ] **Step 1: Write the failing test**

`desktop/src/renderer/__tests__/AccountBackfill.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { ApiError } from '../lib/api/client';
import { AccountBackfill } from '../components/AccountBackfill';
import type { BackfillState } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ...actual, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() };
});

const BASE = '/v1/connectors/gdrive/accounts/me%40x.com/backfill';

function state(over: Partial<BackfillState> = {}): BackfillState {
  return {
    account: 'me@x.com', status: 'running', since: '2023-09-29', cursor: '2026-08',
    pageToken: null, imported: 12, updated: 1, skipped: 3, failed: 0, tooLarge: 2,
    error: null, startedAt: '', updatedAt: '', monthsTotal: 37, monthsDone: 1, ...over,
  };
}

function renderIt(onReauth = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <AccountBackfill connectorId="gdrive" accountId="me@x.com" onReauth={onReauth} />
    </QueryClientProvider>,
  );
  return onReauth;
}

describe('AccountBackfill', () => {
  beforeEach(() => vi.mocked(client.post).mockResolvedValue(state()));
  afterEach(() => vi.clearAllMocks());

  it('offers a backfill with an estimate when none exists', async () => {
    vi.mocked(client.get).mockImplementation(async (path: string) => {
      if (path === BASE) throw new ApiError('none', 404);
      if (path.startsWith(`${BASE}/estimate`)) return { files: 5000, capped: true, since: '2023-09-29' };
      throw new Error(path);
    });
    renderIt();
    fireEvent.click(await screen.findByRole('button', { name: 'backfill…' }));
    expect(await screen.findByText(/~5,000\+ files/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'start backfill' }));
    await waitFor(() => expect(client.post).toHaveBeenCalledWith(BASE, { years: 3 }));
  });

  it('shows running progress with pause and cancel', async () => {
    vi.mocked(client.get).mockResolvedValue(state());
    renderIt();
    expect(await screen.findByText(/backfilling · Aug 2026 · 12 imported · 1 updated · 3 already had · 0 failed · 2 too large/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'pause' }));
    await waitFor(() => expect(client.post).toHaveBeenCalledWith(`${BASE}/pause`));
  });

  it('shows reauthorize on auth error', async () => {
    vi.mocked(client.get).mockResolvedValue(state({ status: 'error', error: 'needs re-auth' }));
    const onReauth = renderIt();
    fireEvent.click(await screen.findByRole('button', { name: 'reauthorize' }));
    expect(onReauth).toHaveBeenCalled();
  });

  it('done state can be dismissed', async () => {
    vi.mocked(client.get).mockResolvedValue(state({ status: 'done' }));
    vi.mocked(client.del).mockResolvedValue({ ok: true });
    renderIt();
    fireEvent.click(await screen.findByRole('button', { name: 'dismiss' }));
    await waitFor(() => expect(client.del).toHaveBeenCalledWith(BASE));
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/AccountBackfill.test.tsx`
Expected: FAIL — component missing.

- [ ] **Step 3: Types** — append to `desktop/src/shared/api-types.ts`:

```ts
export type BackfillStatus = 'running' | 'paused' | 'done' | 'error';

export interface BackfillState {
  account: string;
  status: BackfillStatus;
  since: string;
  cursor: string;
  pageToken: string | null;
  imported: number;
  updated: number;
  skipped: number;
  failed: number;
  tooLarge: number;
  error: string | null;
  startedAt: string;
  updatedAt: string;
  monthsTotal: number;
  monthsDone: number;
}

export interface BackfillEstimate {
  files: number;
  capped: boolean;
  since: string;
}
```

- [ ] **Step 4: Hooks** — append to `desktop/src/renderer/lib/api/hooks.ts` (add `BackfillEstimate`, `BackfillState` to the type import and `ApiError` to the client import if not already imported):

```ts
const backfillPath = (connectorId: string, accountId: string) =>
  `/v1/connectors/${connectorId}/accounts/${encodeURIComponent(accountId)}/backfill`;

/** The account's backfill, or null when none exists (404). Polls every 15 s
 *  while running. Connector-parametrised so Gmail's backfill can share it. */
export function useBackfill(connectorId: string, accountId: string) {
  return useQuery({
    queryKey: ['backfill', connectorId, accountId],
    queryFn: async () => {
      try {
        return await get<BackfillState>(backfillPath(connectorId, accountId));
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null;
        throw e;
      }
    },
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 15_000 : false),
  });
}

export function useBackfillEstimate(connectorId: string, accountId: string, years: number, enabled: boolean) {
  return useQuery({
    queryKey: ['backfill-estimate', connectorId, accountId, years],
    queryFn: () => get<BackfillEstimate>(`${backfillPath(connectorId, accountId)}/estimate?years=${years}`),
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useStartBackfill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: { connectorId: string; accountId: string; years: number }) =>
      post<BackfillState>(backfillPath(a.connectorId, a.accountId), { years: a.years }),
    onSettled: (_d, _e, a) => qc.invalidateQueries({ queryKey: ['backfill', a.connectorId, a.accountId] }),
  });
}

export function useBackfillAction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (a: { connectorId: string; accountId: string; action: 'pause' | 'resume' | 'cancel' }) =>
      a.action === 'cancel'
        ? del(backfillPath(a.connectorId, a.accountId))
        : post<BackfillState>(`${backfillPath(a.connectorId, a.accountId)}/${a.action}`),
    onSettled: (_d, _e, a) => qc.invalidateQueries({ queryKey: ['backfill', a.connectorId, a.accountId] }),
  });
}
```

Check how the existing `ApiError` import/usage looks in `hooks.ts` (the import screen already relies on `status`) and mirror it. Check the `@tanstack/react-query` major in `desktop/package.json`: the `refetchInterval: (q) => q.state.data…` form is v5; on v4 it's `(data) => data?.status…`.

- [ ] **Step 5: Component** — `desktop/src/renderer/components/AccountBackfill.tsx`:

```tsx
import { useState } from 'react';

import { Btn } from './Btn';
import type { BackfillState } from '../../shared/api-types';
import { useBackfill, useBackfillAction, useBackfillEstimate, useStartBackfill } from '../lib/api/hooks';
import { toast } from '../stores/toast';

/** Connectors whose accounts support a backfill. Gmail joins when its branch merges. */
export const BACKFILL_CONNECTORS: ReadonlySet<string> = new Set(['gdrive']);

const YEARS = [1, 2, 3, 5] as const;
const PACE_PER_HOUR = 750;

function monthLabel(cursor: string): string {
  const [y, m] = cursor.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
}

function counts(s: BackfillState): string {
  return `${s.imported} imported · ${s.updated} updated · ${s.skipped} already had · ${s.failed} failed · ${s.tooLarge} too large`;
}

interface Props {
  connectorId: string;
  accountId: string;
  onReauth: () => void;
}

export function AccountBackfill({ connectorId, accountId, onReauth }: Props) {
  const backfill = useBackfill(connectorId, accountId);
  const start = useStartBackfill();
  const act = useBackfillAction();
  const [open, setOpen] = useState(false);
  const [years, setYears] = useState(3);
  const estimate = useBackfillEstimate(connectorId, accountId, years, open && backfill.data === null);

  const onError = (e: unknown) => toast.error(e instanceof Error ? e.message : 'backfill: request failed');
  const run = (action: 'pause' | 'resume' | 'cancel') =>
    act.mutate({ connectorId, accountId, action }, { onError });

  if (backfill.isLoading) return null;
  const s = backfill.data;

  if (s) {
    const line =
      s.status === 'running' ? `backfilling · ${monthLabel(s.cursor)} · ${counts(s)}`
      : s.status === 'paused' ? `backfill paused · ${monthLabel(s.cursor)} · ${counts(s)}`
      : s.status === 'done' ? `backfill complete · ${counts(s)}`
      : `backfill stopped · ${s.error ?? 'error'}`;
    return (
      <div className="flex flex-wrap items-center gap-2 text-11 text-ink-2" data-testid={`backfill-${accountId}`}>
        <span className="min-w-0 flex-1">{line}</span>
        {s.status === 'running' && <Btn variant="ghost" size="sm" onClick={() => run('pause')}>pause</Btn>}
        {s.status === 'paused' && <Btn variant="ghost" size="sm" onClick={() => run('resume')}>resume</Btn>}
        {s.status === 'error' && s.error === 'needs re-auth' && (
          <Btn variant="ghost" size="sm" onClick={onReauth}>reauthorize</Btn>
        )}
        {s.status === 'error' && <Btn variant="ghost" size="sm" onClick={() => run('resume')}>resume</Btn>}
        {s.status === 'done'
          ? <Btn variant="ghost" size="sm" onClick={() => run('cancel')}>dismiss</Btn>
          : <Btn variant="ghost" size="sm" onClick={() => run('cancel')}>cancel</Btn>}
      </div>
    );
  }

  if (!open) {
    return (
      <Btn variant="ghost" size="sm" className="self-start" onClick={() => setOpen(true)}>
        backfill…
      </Btn>
    );
  }

  const est = estimate.data;
  const hours = est ? Math.max(1, Math.round(est.files / PACE_PER_HOUR)) : null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-11 text-ink-2">
      <select
        aria-label={`backfill years for ${accountId}`}
        value={years}
        onChange={(e) => setYears(Number(e.target.value))}
        className="rounded-r6 border border-hairline-2 bg-vellum px-2 py-1 font-mono text-11 text-ink-0"
      >
        {YEARS.map((y) => (
          <option key={y} value={y}>{`${y} year${y > 1 ? 's' : ''}`}</option>
        ))}
      </select>
      <span className="min-w-0 flex-1">
        {estimate.isLoading && 'estimating…'}
        {estimate.isError && (estimate.error instanceof Error ? estimate.error.message : 'estimate failed')}
        {est && `~${est.files.toLocaleString('en-US')}${est.capped ? '+' : ''} files · about ${hours} h at the current pace`}
      </span>
      <Btn
        variant="secondary"
        size="sm"
        disabled={start.isPending}
        onClick={() =>
          start.mutate({ connectorId, accountId, years }, { onSuccess: () => setOpen(false), onError })
        }
      >
        start backfill
      </Btn>
      <Btn variant="ghost" size="sm" onClick={() => setOpen(false)}>close</Btn>
    </div>
  );
}
```

A 409 "Scheduler not running" from start surfaces through `onError` as a toast with the server's message.

- [ ] **Step 6: Wire it in + catalog card**

In `ConnectorAccounts.tsx`, import `{ AccountBackfill, BACKFILL_CONNECTORS }` and inside each account row, after the context/enabled row `</div>`:

```tsx
            {BACKFILL_CONNECTORS.has(connector.id) && (
              <AccountBackfill connectorId={connector.id} accountId={a.id} onReauth={() => onReauth(a.id)} />
            )}
```

In `connector-catalog.ts`, after the `calendar` card:

```ts
  {
    id: 'gdrive',
    displayName: 'Google Drive',
    blurb: 'Hourly, imports Google Docs, Sheets, PDFs and Word/Excel files you own or edited — one note per file, updated in place. Backfill older files per account.',
    pattern: 'google_oauth',
    docsUrl: 'https://console.cloud.google.com/apis/library',
    group: 'google',
  },
```

If `connector-catalog.test.ts` asserts the exact list/count of cards or google group members, update it to include `gdrive`.

- [ ] **Step 7: Run tests + typecheck**

Run: `cd desktop && npx vitest run src/renderer/__tests__/AccountBackfill.test.tsx src/renderer/__tests__/ConnectorAccounts.test.tsx src/renderer/__tests__/connector-catalog.test.ts && npm run typecheck`
Expected: PASS, typecheck clean. (`ConnectorAccounts.test.tsx` uses `id: 'gmail'`, so no backfill row renders there and it stays green.)

- [ ] **Step 8: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector && git add desktop/src && git commit -m "feat(gdrive): desktop card, backfill hooks and per-account backfill UI

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Docs, full verification, live smoke test

**Files:**
- Modify: `docs/connectors.md`, `.claude/skills/poltergeist-setup/SKILL.md`, `.claude/skills/poltergeist-setup/checks.md`

- [ ] **Step 1: Docs**

`docs/connectors.md`: add `- [Google Drive](#google-drive)` to the TOC after Gmail, add `gdrive` to the account-bearing connector list on line 17, and a section after `## Gmail`:

```markdown
## Google Drive

Imports Google Docs, Google Sheets, PDFs, Word (.docx) and Excel (.xlsx) files **you own or have edited** — one note per file under `20-contexts/<ctx>/gdrive/`, named `<title>-<fileId>.md` and updated in place when the file changes (its context is kept; no re-routing). Docs only shared with you are ignored.

### One-time setup

1. Reuse the Desktop OAuth client from Gmail/Calendar (`~/.ghostbrain/state/google_oauth_client.json`).
2. In that client's Google Cloud project, enable **Google Drive API**, **Google Docs API** and **Google Sheets API** (APIs & Services → Library). A missing one shows up as "Enable the Google X API…" on the connector.
3. Connect in the app: Connectors → Google Drive → add account.

### Run

- Hourly sync: files modified since the last run (first run: last 7 days). Files edited in the last 30 minutes wait for the next run.
- Backfill: Connectors → Google Drive → account → **backfill…** (1–5 years). Runs in the in-app scheduler, 25 files every 2 minutes; pause/resume/cancel any time — imported notes stay.

### Limits

Files over 200 MB are skipped. Sheets: first 50 tabs, 5,000 rows × 50 columns per tab. Note bodies are capped at 1M characters. Truncation is marked in the note.
```

`.claude/skills/poltergeist-setup/SKILL.md` line ~72: add "Google Drive" to the connector list. `checks.md`: in the `connectors` check paragraph add `gdrive` to the accounts.yaml-configured connectors (`gmail`, `gdrive`, `slack`, …), and to the consent-screen caveat add "Google Drive" alongside Gmail and Google Calendar plus: "Drive also needs the Drive, Docs and Sheets APIs enabled on that client's project."

- [ ] **Step 2: Full verification**

Run:
```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector && .venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_recorder_wasapi_io.py 2>&1 | tail -30
.venv/bin/python -m ruff check ghostbrain/connectors/gdrive tests/gdrive_fakes.py tests/test_gdrive_*.py ghostbrain/api/tests/test_gdrive_*.py
cd desktop && npx vitest run && npm run typecheck
```
Expected: Python = baseline 22 failures (same files as Global Constraints) and every `gdrive` test passing; ruff clean; vitest green; typecheck clean.

- [ ] **Step 3: Commit docs**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector && git add docs/connectors.md .claude/skills/poltergeist-setup && git commit -m "docs(gdrive): connector setup, backfill and limits

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Live smoke test (needs the user)**

Against a real Google account, in a throwaway vault so the real vault isn't touched:

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/gdrive-connector
export VAULT_PATH=/private/tmp/gdrive-smoke/vault GHOSTBRAIN_STATE_DIR=/private/tmp/gdrive-smoke/state
mkdir -p $GHOSTBRAIN_STATE_DIR && cp ~/.ghostbrain/state/google_oauth_client.json $GHOSTBRAIN_STATE_DIR/
.venv/bin/python -c "from ghostbrain.bootstrap import bootstrap; import pathlib, os; bootstrap(pathlib.Path(os.environ['VAULT_PATH']))"
.venv/bin/python -c "from ghostbrain.connectors.gdrive import auth; from ghostbrain import accounts; e='<USER EMAIL>'; auth.run_oauth_flow(e); accounts.ensure_account('gdrive', e)"
.venv/bin/python -c "from ghostbrain.connectors.gdrive import runner; print(runner.run())"
.venv/bin/python -c "from datetime import date; from ghostbrain.connectors.gdrive import backfill as b; print(b.estimate('<USER EMAIL>', since=date(2026,6,1))); b.start('<USER EMAIL>', since=date(2026,8,1)); [print(b.run_tick()) for _ in range(6)]"
ls -R $VAULT_PATH/00-inbox/raw/gdrive | head; 
```

Ask the user to run the OAuth line themselves (`! <command>`) — it opens a browser. Check: at least one Doc, one Sheet and one PDF/DOCX note exist with readable bodies; edit a Doc in Drive, wait 31 min (or temporarily run with `DEBOUNCE` patched), re-run the sync and confirm the same file was rewritten (no second note). Report what was seen; don't mark done on unit tests alone.
```
