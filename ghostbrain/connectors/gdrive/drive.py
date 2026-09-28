"""Thin helpers over the Drive v3 / Docs v1 / Sheets v4 discovery clients:
building services, the modifiedTime-windowed query, paging, error mapping
(rate limits → retry, API disabled → clear message, 401 → re-auth), folder
paths and streaming downloads."""
from __future__ import annotations

import dataclasses
import json
import logging
import time
from datetime import UTC, datetime
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
# Same set as Gmail's backfill: quota 403s are transient, never "re-auth".
_RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded", "quotaExceeded"}
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
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: FURB162
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


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


def _map_http_error(e: HttpError, api: str, *, retries: int = MAX_RETRIES) -> BaseException:
    """The exception ``e`` stands for: ``DriveApiDisabled``, ``GdriveAuthError``
    (401), ``DriveRateLimited`` (429, 5xx or a rate/quota 403 — callers may
    retry first) or ``e`` itself for anything else."""
    status = e.resp.status
    why = reasons(e)
    if why & _DISABLED_REASONS:
        return DriveApiDisabled(api)
    if status == 401:
        return GdriveAuthError(f"Google rejected the Drive token ({api} API). Reauthorize.")
    if status == 429 or status >= 500 or (status == 403 and bool(why & _RATE_REASONS)):
        return DriveRateLimited(f"{api} API still rate-limited after {retries} retries")
    return e


def execute(request, *, api: str = "Drive"):
    for attempt in range(MAX_RETRIES + 1):
        try:
            return request.execute()
        except HttpError as e:
            mapped = _map_http_error(e, api)
            if mapped is e:
                raise
            if isinstance(mapped, DriveRateLimited) and attempt < MAX_RETRIES:
                _sleep(BACKOFF_BASE_SECONDS * (2 ** attempt))
                continue
            raise mapped from e
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
    except Exception:
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
            try:
                # next_chunk already retries 429/5xx itself (num_retries).
                _, done = downloader.next_chunk(num_retries=MAX_RETRIES)
            except HttpError as e:
                mapped = _map_http_error(e, "Drive")
                if mapped is e:
                    raise
                raise mapped from e
