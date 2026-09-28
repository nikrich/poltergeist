"""Gmail backfill — index past threads the user took part in.

One state file per account at <state>/gmail_backfill.<slug>.json; the in-app
scheduler calls run_tick() every 2 minutes and each tick processes one small
batch for one running backfill, newest month first. Threads go through the
normal worker pipeline (routing: rules → account context → LLM) without the
daily sync's relevance gate. Imported notes are never removed by cancel.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

from ghostbrain import accounts
from ghostbrain.connectors.gmail.auth import GmailAuthError, load_credentials, token_path
from ghostbrain.connectors.gmail.connector import (
    _is_denied,
    _is_promotional,
    _normalize_thread,
)
from ghostbrain.paths import state_dir, vault_path

log = logging.getLogger("ghostbrain.connectors.gmail.backfill")

QUERY_BASE = "(from:me OR is:starred OR is:important) -category:promotions"
BATCH_SIZE = 25
MAX_YEARS = 10
NUM_RETRIES = 3  # googleapiclient built-in backoff per request

AUTH_ERROR_MESSAGE = "needs re-auth"
_STATE_PREFIX = "gmail_backfill."

_lock = threading.Lock()


def _today() -> date:
    return datetime.now(UTC).astimezone().date()  # local calendar day


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# State file helpers
# ---------------------------------------------------------------------------


def _state_path(account: str) -> Path:
    slug = token_path(account).stem.split(".", 1)[1]
    return state_dir() / f"{_STATE_PREFIX}{slug}.json"


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _update(account: str, **fields) -> dict | None:
    """Merge ``fields`` into the on-disk state under the lock.

    Re-reads first so a pause/cancel issued mid-tick is never overwritten.
    Returns the new state, or None when the state file is gone."""
    path = _state_path(account)
    with _lock:
        state = _read(path)
        if state is None:
            return None
        state.update(fields)
        state["updatedAt"] = _now().isoformat()
        _write(path, state)
        return state


# ---------------------------------------------------------------------------
# Month arithmetic ("YYYY-MM" cursors)
# ---------------------------------------------------------------------------


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_start(key: str) -> date:
    return date(int(key[:4]), int(key[5:7]), 1)


def _next_month(first: date) -> date:
    return date(first.year + (first.month == 12), first.month % 12 + 1, 1)


def _prev_month_key(key: str) -> str:
    return _month_key(_month_start(key) - timedelta(days=1))


def _month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def _clamp_since(since: date) -> date:
    today = _today()
    try:
        floor = today.replace(year=today.year - MAX_YEARS)
    except ValueError:  # Feb 29 → Feb 28
        floor = today.replace(year=today.year - MAX_YEARS, day=28)
    return max(since, floor)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start(account: str, *, since: date) -> dict:
    """Create a running backfill (or return the existing unfinished one)."""
    if accounts.get_account("gmail", account) is None:
        raise KeyError(account)
    path = _state_path(account)
    with _lock:
        existing = _read(path)
        if existing is not None and existing.get("status") != "done":
            return existing
        now = _now().isoformat()
        state = {
            "account": account,
            "status": "running",
            "since": _clamp_since(since).isoformat(),
            "cursor": _month_key(_today()),
            "pageToken": None,
            "imported": 0,
            "skipped": 0,
            "failed": 0,
            "error": None,
            "startedAt": now,
            "updatedAt": now,
        }
        _write(path, state)
        return state


def get(account: str) -> dict | None:
    state = _read(_state_path(account))
    if state is None:
        return None
    try:
        since = date.fromisoformat(state["since"])
        started = datetime.fromisoformat(state["startedAt"]).date()
        cursor = _month_start(state["cursor"])
    except (KeyError, TypeError, ValueError):
        return state
    total = max(0, _month_index(started) - _month_index(since) + 1)
    done = total if state.get("status") == "done" else (
        min(total, max(0, _month_index(started) - _month_index(cursor)))
    )
    return {**state, "monthsTotal": total, "monthsDone": done}


def _set_status(account: str, status: str, **extra) -> dict | None:
    return _update(account, status=status, **extra)


def pause(account: str) -> dict | None:
    return _set_status(account, "paused")


def resume(account: str) -> dict | None:
    return _set_status(account, "running", error=None)


def cancel(account: str) -> bool:
    path = _state_path(account)
    with _lock:
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True


def estimate(account: str, *, since: date, service_factory=None) -> int:
    """Gmail's ``resultSizeEstimate`` for the whole backfill range.
    Raises ``GmailAuthError`` when the account needs re-auth."""
    try:
        service = (service_factory or _build_service)(account)
        resp = service.users().threads().list(
            userId="me", q=f"{QUERY_BASE} after:{since:%Y/%m/%d}", maxResults=1,
        ).execute(num_retries=NUM_RETRIES)
    except Exception as e:
        if _classify(e) == "auth" and not isinstance(e, GmailAuthError):
            raise GmailAuthError(AUTH_ERROR_MESSAGE) from e
        raise
    try:
        return int(resp.get("resultSizeEstimate") or 0)
    except (TypeError, ValueError):
        return 0


def run_tick(
    *,
    batch_size: int = BATCH_SIZE,
    service_factory: Callable | None = None,
    process: Callable[[dict], dict] | None = None,
) -> dict:
    """Process one batch for the running backfill updated least recently.

    Never raises for Gmail/network trouble: auth failures park the backfill
    in ``error``; transient failures record ``error`` (type name only), keep
    it ``running`` and leave cursor/pageToken alone so the page is retried
    (dedup makes that idempotent)."""
    state = _pick_next()
    if state is None:
        return {"skipped": "idle"}
    account = state["account"]
    if process is None:
        from ghostbrain.worker.pipeline import process_event as process

    counts = {"imported": 0, "skipped": 0, "failed": 0}

    def summary(st: dict | None) -> dict:
        if st is None:  # cancelled mid-tick
            return {"skipped": "cancelled", "account": account}
        return {"account": account, "status": st.get("status"), **counts,
                "cursor": st.get("cursor")}

    def gmail_failed(e: Exception) -> dict:
        if _classify(e) == "auth":
            return summary(_auth_failed(account))
        log.warning("gmail backfill %s: transient %s; retrying next tick",
                    account, type(e).__name__)
        return summary(_update(account, error=type(e).__name__))

    cursor = state["cursor"]
    first = _month_start(cursor)
    query = (f"{QUERY_BASE} after:{first:%Y/%m/%d} "
             f"before:{_next_month(first):%Y/%m/%d}")
    try:
        service = (service_factory or _build_service)(account)
        resp = service.users().threads().list(
            userId="me", q=query, maxResults=batch_size,
            pageToken=state.get("pageToken"),
        ).execute(num_retries=NUM_RETRIES)
    except Exception as e:  # noqa: BLE001 — classified in gmail_failed
        return gmail_failed(e)

    existing = _existing_gmail_ids()
    denylist = _denylist()
    for stub in resp.get("threads") or []:
        tid = stub.get("id")
        if not tid:
            continue
        try:
            full = service.users().threads().get(
                userId="me", id=tid, format="full",
            ).execute(num_retries=NUM_RETRIES)
        except Exception as e:  # noqa: BLE001
            if _classify(e) != "thread":
                return gmail_failed(e)
            log.warning("gmail backfill %s: thread %s failed: %s",
                        account, tid, type(e).__name__)
            outcome = "failed"
        else:
            try:
                outcome = _import_thread(full, account, existing, denylist, process)
            except Exception as e:  # noqa: BLE001
                log.warning("gmail backfill %s: thread %s failed: %s",
                            account, tid, type(e).__name__)
                outcome = "failed"
        counts[outcome] += 1
        new = _update(account, **{outcome: int(state.get(outcome) or 0) + 1})
        if new is None:
            return summary(None)
        state = new
        if state.get("status") != "running":
            return summary(state)

    token = resp.get("nextPageToken")
    fields: dict = {"error": None}
    if token:
        fields["pageToken"] = token
    else:
        last_day = _month_start(cursor) - timedelta(days=1)
        fields.update(cursor=_prev_month_key(cursor), pageToken=None)
        if last_day < date.fromisoformat(state["since"]):
            fields["status"] = "done"
    return summary(_update(account, **fields))


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _classify(exc: BaseException) -> str:
    """``auth`` (needs re-auth), ``transient`` (retry the page later) or
    ``thread`` (this one thread is bad; count it and move on)."""
    # Lazy imports: the google client stack is heavy and only needed on error.
    from google.auth.exceptions import RefreshError
    from googleapiclient.errors import HttpError
    from httplib2 import HttpLib2Error

    if isinstance(exc, (GmailAuthError, RefreshError)):
        return "auth"
    if isinstance(exc, HttpError):
        status = int(getattr(exc, "status_code", None) or getattr(exc.resp, "status", 0) or 0)
        if status in (401, 403):
            return "auth"
        if status == 429 or status >= 500:
            return "transient"
        return "thread"
    if isinstance(exc, (OSError, TimeoutError, HttpLib2Error)):
        return "transient"
    return "thread"


def _import_thread(full, account, existing, denylist, process) -> str:
    event = _normalize_thread(full, account=account)
    if event is None or _is_denied(event, denylist) or _is_promotional(event):
        return "skipped"
    if event["id"] in existing:
        return "skipped"
    process(event)
    existing.add(event["id"])
    return "imported"


def _auth_failed(account: str) -> dict | None:
    log.warning("gmail backfill %s: %s", account, AUTH_ERROR_MESSAGE)
    return _update(account, status="error", error=AUTH_ERROR_MESSAGE)


def _pick_next() -> dict | None:
    """The running state with the oldest ``updatedAt`` whose account is
    enabled. States of accounts removed from the registry are deleted —
    but only when the registry actually loaded: an empty result (missing,
    unreadable or malformed accounts.yaml) must never wipe backfills."""
    registry = {
        a.id.lower(): a
        for a in accounts.list_accounts("gmail", include_disabled=True)
    }
    if not registry:
        return None
    candidates: list[dict] = []
    for path in sorted(state_dir().glob(f"{_STATE_PREFIX}*.json")):
        st = _read(path)
        if not st or st.get("status") != "running" or not st.get("account"):
            continue
        acc = registry.get(str(st["account"]).lower())
        if acc is None:
            log.info("gmail backfill %s: account removed; cancelling", st["account"])
            with _lock:
                path.unlink(missing_ok=True)
            continue
        if not acc.enabled:
            continue
        candidates.append(st)
    if not candidates:
        return None
    return min(candidates, key=lambda s: str(s.get("updatedAt") or ""))


def _existing_gmail_ids() -> set[str]:
    vault = vault_path()
    paths = list((vault / "00-inbox" / "raw" / "gmail").glob("*.md"))
    paths.extend((vault / "20-contexts").glob("*/gmail/**/*.md"))
    ids: set[str] = set()
    for p in paths:
        fid = _frontmatter_id(p)
        if fid:
            ids.add(fid)
    return ids


def _frontmatter_id(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    fid = fm.get("id") if isinstance(fm, dict) else None
    return str(fid) if fid else None


def _denylist() -> list[str]:
    try:
        routing = yaml.safe_load(
            (vault_path() / "90-meta" / "routing.yaml").read_text(encoding="utf-8")
        ) or {}
    except (OSError, yaml.YAMLError):
        return []
    gmail = routing.get("gmail") if isinstance(routing, dict) else None
    if not isinstance(gmail, dict):
        return []
    return [str(d).lower() for d in gmail.get("denylist_domains") or []]


def _build_service(account: str):
    from googleapiclient.discovery import build  # lazy — heavy
    creds = load_credentials(account)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)
