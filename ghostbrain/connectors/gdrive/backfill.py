"""Google Drive backfill — index past files the user owns or edited.

One state file per account at <state>/gdrive_backfill.<slug>.json; the in-app
scheduler calls run_tick() every 2 minutes and each tick works through one
page of up to 100 listed files for one running backfill, newest month first
(by ``modifiedTime``), processing at most 25 of the user's own files.
Files go through ``ingest.ingest_file`` (the same path as the hourly sync),
which upserts: new files become notes, changed ones are rewritten in place,
unchanged ones are skipped. Imported notes are never removed by cancel.

Same state machine and guards as the Gmail backfill
(``ghostbrain/connectors/gmail/backfill.py``); a shared base is a follow-up.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path

from ghostbrain import accounts
from ghostbrain.connectors.gdrive import drive, ingest
from ghostbrain.connectors.gdrive.auth import GdriveAuthError, slug
from ghostbrain.paths import state_dir

log = logging.getLogger("ghostbrain.connectors.gdrive.backfill")

BATCH_SIZE = 25  # the user's files (owned or edited) processed per tick
LIST_PAGE_SIZE = 100  # files listed per page; most may be other people's
MAX_YEARS = 10
ESTIMATE_CAP = 5000
ESTIMATE_PAGE_SIZE = 1000
ESTIMATE_FIELDS = "id,ownedByMe,modifiedByMe"

TICK_BUDGET_SECONDS = 60  # stop taking new files once a tick ran this long
ROUTING_FALLBACK_LIMIT = 5  # consecutive LLM-routing failures before pausing

AUTH_ERROR_MESSAGE = "needs re-auth"
ROUTING_ERROR_MESSAGE = "AI routing unavailable — resume later"
_STATE_PREFIX = "gdrive_backfill."
_COUNTERS = ingest.OUTCOMES  # imported, updated, skipped, failed, tooLarge

_services_for = drive.build_services
_lock = threading.Lock()


def _today() -> date:
    return datetime.now(UTC).astimezone().date()  # local calendar day


def _now() -> datetime:
    return datetime.now(UTC)


def _monotonic() -> float:
    return time.monotonic()


# ---------------------------------------------------------------------------
# State file helpers
# ---------------------------------------------------------------------------


def state_path(account: str) -> Path:
    return state_dir() / f"{_STATE_PREFIX}{slug(account)}.json"


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


def _update(
    account: str,
    *,
    _started: str | None = None,
    _incr: dict[str, int] | None = None,
    **fields,
) -> dict | None:
    """Merge ``fields`` into the on-disk state under the lock.

    Re-reads first so a pause/cancel issued mid-tick is never overwritten.
    ``_incr`` adds to counters of the re-read state. With ``_started`` the
    write only happens while the stored ``startedAt`` still matches (i.e. the
    backfill was not cancelled and restarted meanwhile).
    Returns the new state, or None when the state file is gone / replaced."""
    path = state_path(account)
    with _lock:
        state = _read(path)
        if state is None:
            return None
        if _started is not None and state.get("startedAt") != _started:
            return None
        for key, n in (_incr or {}).items():
            state[key] = int(state.get(key) or 0) + n
        state.update(fields)
        state["updatedAt"] = _now().isoformat()
        _write(path, state)
        return state


# ---------------------------------------------------------------------------
# Month arithmetic ("YYYY-MM" cursors) and Drive windows
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


def _midnight_utc(d: date) -> datetime:
    return datetime.combine(d, dtime(0, 0), tzinfo=UTC)


def _after(d: date) -> datetime:
    """Lower bound for ``modifiedTime >`` (strict): one second before
    ``d`` 00:00 UTC so a file modified at exactly midnight is included."""
    return _midnight_utc(d) - timedelta(seconds=1)


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
    if accounts.get_account("gdrive", account) is None:
        raise KeyError(account)
    path = state_path(account)
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
            "pageDone": [],
            **{key: 0 for key in _COUNTERS},
            "routingFallbacks": 0,
            "error": None,
            "startedAt": now,
            "updatedAt": now,
        }
        _write(path, state)
        return state


def get(account: str) -> dict | None:
    state = _read(state_path(account))
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


def pause(account: str) -> dict | None:
    return _update(account, status="paused")


def resume(account: str) -> dict | None:
    return _update(account, status="running", error=None, routingFallbacks=0)


def cancel(account: str) -> bool:
    path = state_path(account)
    with _lock:
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True


def estimate(account: str, *, since: date) -> dict:
    """How many files the backfill would consider (owned or edited by the
    account), counted up to ``ESTIMATE_CAP``. ``GdriveAuthError`` and
    ``drive.DriveApiDisabled`` propagate."""
    try:
        services = _services_for(account)
        after = _after(since)
        count = 0
        token: str | None = None
        while True:
            files, token = drive.list_page(
                services.drive, after=after, page_token=token,
                page_size=ESTIMATE_PAGE_SIZE, fields=ESTIMATE_FIELDS,
            )
            count += sum(1 for f in files if drive.is_mine(f))
            if count >= ESTIMATE_CAP:
                return {"files": ESTIMATE_CAP, "capped": True}
            if not token:
                return {"files": count, "capped": False}
    except Exception as e:
        if _classify(e) == "auth" and not isinstance(e, GdriveAuthError):
            raise GdriveAuthError(AUTH_ERROR_MESSAGE) from e
        raise


def run_tick(*, batch_size: int = BATCH_SIZE) -> dict:
    """Process one page for the running backfill updated least recently.

    Lists ``LIST_PAGE_SIZE`` files and processes at most ``batch_size`` of
    the user's own ones; files that aren't theirs cost nothing, so a page
    of mostly shared files no longer takes a whole tick for a handful.

    Never raises for Drive/network trouble: auth failures and a disabled API
    park the backfill in ``error``; transient failures record ``error`` (type
    name only), keep it ``running`` and leave cursor/pageToken/pageDone alone
    so the page is retried (upserts make that idempotent).

    Every write is tied to the ``startedAt`` of the state this tick picked:
    once the backfill was cancelled (and maybe restarted) the tick ends
    without touching the new state. The tick stops taking new files after
    ``TICK_BUDGET_SECONDS`` or after ``batch_size`` files; the handled file
    ids are kept in ``pageDone`` and cursor/pageToken only advance once the
    whole page was handled."""
    t0 = _monotonic()
    state = _pick_next()
    if state is None:
        return {"skipped": "idle"}
    account = state["account"]
    started = state.get("startedAt")
    counts = {key: 0 for key in _COUNTERS}

    def update(**fields) -> dict | None:
        return _update(account, _started=started, **fields)

    def summary(st: dict | None) -> dict:
        if st is None:  # cancelled mid-tick
            return {"skipped": "cancelled", "account": account}
        return {"account": account, "status": st.get("status"), **counts,
                "cursor": st.get("cursor")}

    def drive_failed(e: BaseException) -> dict:
        kind = _classify(e)
        if kind == "auth":
            log.warning("gdrive backfill %s: %s", account, AUTH_ERROR_MESSAGE)
            return summary(update(status="error", error=AUTH_ERROR_MESSAGE))
        if kind == "disabled":
            log.warning("gdrive backfill %s: %s", account, e)
            return summary(update(status="error", error=str(e)))
        log.warning("gdrive backfill %s: transient %s; retrying next tick",
                    account, type(e).__name__)
        return summary(update(error=type(e).__name__))

    cursor = state["cursor"]
    page_token = state.get("pageToken")
    since = date.fromisoformat(state["since"])
    first = _month_start(cursor)
    try:
        services = _services_for(account)
        files, next_token = drive.list_page(
            services.drive,
            after=_after(max(first, since)),
            before=_midnight_utc(_next_month(first)),
            page_token=page_token,
            page_size=LIST_PAGE_SIZE,
        )
    except Exception as e:  # noqa: BLE001 — classified below
        status = _rejected_status(e)
        if status is None:
            return drive_failed(e)
        if page_token and status in (400, 404):
            # A stale/invalid page token: redo the month from the start
            # (upserts make that safe).
            log.warning("gdrive backfill %s: list rejected (%s) with a page "
                        "token; restarting month %s", account, status, cursor)
            return summary(update(pageToken=None, pageDone=[],
                                  error=type(e).__name__))
        log.warning("gdrive backfill %s: query rejected (%s)", account, status)
        return summary(update(status="error",
                              error=f"Drive rejected the query ({status})"))

    done_ids: list[str] = [str(i) for i in state.get("pageDone") or []]
    seen = set(done_ids)
    todo = [f for f in files
            if f.get("id") and f["id"] not in seen and drive.is_mine(f)]
    folders: dict = {}
    for i, f in enumerate(todo):
        try:
            outcome, fallback = ingest.ingest_file(services, account, f, folders)
        except Exception as e:  # noqa: BLE001 — only account-level errors escape
            return drive_failed(e)
        counts[outcome] += 1
        done_ids.append(f["id"])
        fields: dict = {"pageDone": done_ids}
        if outcome == "imported":
            streak = int(state.get("routingFallbacks") or 0) + 1 if fallback else 0
            fields["routingFallbacks"] = streak
            if streak >= ROUTING_FALLBACK_LIMIT:
                log.warning("gdrive backfill %s: %d files in a row fell back "
                            "to needs_review; pausing", account, streak)
                fields.update(status="error", error=ROUTING_ERROR_MESSAGE)
        remaining = i + 1 < len(todo)
        over_budget = remaining and _monotonic() - t0 >= TICK_BUDGET_SECONDS
        batch_full = remaining and i + 1 >= batch_size
        if over_budget or batch_full:
            fields.setdefault("error", None)  # never clobber the routing pause
        new = update(_incr={outcome: 1}, **fields)
        if new is None:
            return summary(None)
        state = new
        if state.get("status") != "running":
            return summary(state)
        if over_budget or batch_full:
            log.info("gdrive backfill %s: %s; continuing the page next tick", account,
                     "tick budget used" if over_budget else f"{batch_size} files processed")
            return summary(state)

    fields = {"error": None, "pageDone": []}
    if next_token:
        fields["pageToken"] = next_token
    else:
        fields.update(cursor=_prev_month_key(cursor), pageToken=None)
        if first <= since:
            fields["status"] = "done"
    return summary(update(**fields))


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _http_status(exc) -> int:
    return int(getattr(exc, "status_code", None) or getattr(exc.resp, "status", 0) or 0)


def _classify(exc: BaseException) -> str:
    """``auth`` (needs re-auth), ``disabled`` (enable the API), ``transient``
    (retry the page later) or ``rejected`` (Drive refused the request: a
    non-auth, non-transient 4xx)."""
    # Lazy imports: the google client stack is heavy and only needed on error.
    from google.auth.exceptions import RefreshError
    from googleapiclient.errors import HttpError
    from httplib2 import HttpLib2Error

    if isinstance(exc, (GdriveAuthError, RefreshError)):
        return "auth"
    if isinstance(exc, drive.DriveApiDisabled):
        return "disabled"
    if isinstance(exc, drive.DriveRateLimited):
        return "transient"
    if isinstance(exc, HttpError):
        status = _http_status(exc)
        if status == 401:
            return "auth"
        if status == 429 or status >= 500:
            return "transient"
        if status == 403:
            # Rate-limit and API-disabled 403s already arrive as
            # DriveRateLimited / DriveApiDisabled (drive.execute); what is
            # left (insufficientPermissions, forbidden, …) means the token
            # can't read Drive — re-auth, as Gmail treats permission 403s.
            return "auth"
        return "rejected"
    if isinstance(exc, (OSError, TimeoutError, HttpLib2Error)):
        return "transient"
    # Anything else (e.g. an unexpected error from the Drive client): keep the
    # backfill running and retry the page next tick. Gmail instead counts an
    # unknown per-thread error as "thread" (failed); here per-file errors are
    # already absorbed by ingest_file, so only list/account-level ones get here.
    return "transient"


def _rejected_status(exc: BaseException) -> int | None:
    """The HTTP status when Drive rejected a request with a non-auth,
    non-transient 4xx (bad query / page token); else None."""
    from googleapiclient.errors import HttpError  # lazy — heavy

    if not isinstance(exc, HttpError) or _classify(exc) != "rejected":
        return None
    status = _http_status(exc)
    return status if 400 <= status < 500 else None


def _pick_next() -> dict | None:
    """The running state with the oldest ``updatedAt`` whose account is
    enabled. States of accounts removed from the registry are deleted —
    but only when the registry actually loaded: an empty or failing result
    (missing, unreadable or malformed accounts.yaml) never wipes backfills."""
    try:
        registry = {
            a.id.lower(): a
            for a in accounts.list_accounts("gdrive", include_disabled=True)
        }
    except Exception:
        log.warning("gdrive backfill: account registry unreadable; skipping tick",
                    exc_info=True)
        return None
    if not registry:
        return None
    candidates: list[dict] = []
    for path in sorted(state_dir().glob(f"{_STATE_PREFIX}*.json")):
        st = _read(path)
        if not st or st.get("status") != "running" or not st.get("account"):
            continue
        acc = registry.get(str(st["account"]).lower())
        if acc is None:
            log.info("gdrive backfill %s: account removed; cancelling", st["account"])
            with _lock:
                path.unlink(missing_ok=True)
            continue
        if not acc.enabled:
            continue
        candidates.append(st)
    if not candidates:
        return None
    return min(candidates, key=lambda s: str(s.get("updatedAt") or ""))
