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
import time
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

TICK_BUDGET_SECONDS = 60  # stop taking new threads once a tick ran this long
ROUTING_FALLBACK_LIMIT = 5  # consecutive LLM-routing failures before pausing

AUTH_ERROR_MESSAGE = "needs re-auth"
ROUTING_ERROR_MESSAGE = "AI routing unavailable — resume later"
_STATE_PREFIX = "gmail_backfill."

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
    path = _state_path(account)
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
    return _set_status(account, "running", error=None, routingFallbacks=0)


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
    (dedup makes that idempotent).

    Every write is tied to the ``startedAt`` of the state this tick picked:
    once the backfill was cancelled (and maybe restarted) the tick ends
    without touching the new state. The tick stops taking new threads after
    ``TICK_BUDGET_SECONDS``; the handled thread ids are kept in ``pageDone``
    and cursor/pageToken only advance once the whole page was handled."""
    t0 = _monotonic()
    state = _pick_next()
    if state is None:
        return {"skipped": "idle"}
    account = state["account"]
    started = state.get("startedAt")
    if process is None:
        from ghostbrain.worker.pipeline import process_event as process

    counts = {"imported": 0, "skipped": 0, "failed": 0}

    def update(**fields) -> dict | None:
        return _update(account, _started=started, **fields)

    def summary(st: dict | None) -> dict:
        if st is None:  # cancelled mid-tick
            return {"skipped": "cancelled", "account": account}
        return {"account": account, "status": st.get("status"), **counts,
                "cursor": st.get("cursor")}

    def gmail_failed(e: Exception) -> dict:
        if _classify(e) == "auth":
            log.warning("gmail backfill %s: %s", account, AUTH_ERROR_MESSAGE)
            return summary(update(status="error", error=AUTH_ERROR_MESSAGE))
        log.warning("gmail backfill %s: transient %s; retrying next tick",
                    account, type(e).__name__)
        return summary(update(error=type(e).__name__))

    cursor = state["cursor"]
    page_token = state.get("pageToken")
    first = _month_start(cursor)
    query = (f"{QUERY_BASE} after:{first:%Y/%m/%d} "
             f"before:{_next_month(first):%Y/%m/%d}")
    try:
        service = (service_factory or _build_service)(account)
        resp = service.users().threads().list(
            userId="me", q=query, maxResults=batch_size,
            pageToken=page_token,
        ).execute(num_retries=NUM_RETRIES)
    except Exception as e:  # noqa: BLE001 — classified below
        status = _rejected_status(e)
        if status is None:
            return gmail_failed(e)
        if page_token:
            # A stale/invalid page token: redo the month from the start
            # (dedup makes that safe).
            log.warning("gmail backfill %s: list rejected (%s) with a page "
                        "token; restarting month %s", account, status, cursor)
            return summary(update(pageToken=None, pageDone=[],
                                  error=type(e).__name__))
        log.warning("gmail backfill %s: query rejected (%s)", account, status)
        return summary(update(status="error",
                              error=f"Gmail rejected the query ({status})"))

    stubs = [s for s in (resp.get("threads") or []) if s.get("id")]
    done_ids: list[str] = [str(i) for i in state.get("pageDone") or []]
    todo = [s for s in stubs if s["id"] not in set(done_ids)]
    existing = _existing_gmail_ids()
    denylist = _denylist()
    for i, stub in enumerate(todo):
        tid = stub["id"]
        routing_fallback: bool | None = None
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
                outcome, result = _import_thread(full, account, existing, denylist, process)
            except Exception as e:  # noqa: BLE001
                log.warning("gmail backfill %s: thread %s failed: %s",
                            account, tid, type(e).__name__)
                outcome = "failed"
            else:
                if outcome == "imported":
                    routing_fallback = _is_routing_fallback(result)
        counts[outcome] += 1
        done_ids.append(tid)
        fields: dict = {}
        if routing_fallback is not None:
            streak = (int(state.get("routingFallbacks") or 0) + 1
                      if routing_fallback else 0)
            fields["routingFallbacks"] = streak
            if streak >= ROUTING_FALLBACK_LIMIT:
                log.warning("gmail backfill %s: %d threads in a row fell back "
                            "to needs_review; pausing", account, streak)
                fields.update(status="error", error=ROUTING_ERROR_MESSAGE,
                              pageDone=done_ids)
        remaining = i + 1 < len(todo)
        over_budget = remaining and _monotonic() - t0 >= TICK_BUDGET_SECONDS
        if over_budget:
            fields.update(pageDone=done_ids, error=None)
        new = update(_incr={outcome: 1}, **fields)
        if new is None:
            return summary(None)
        state = new
        if state.get("status") != "running":
            return summary(state)
        if over_budget:
            log.info("gmail backfill %s: tick budget used; continuing next tick",
                     account)
            return summary(state)

    token = resp.get("nextPageToken")
    fields = {"error": None, "pageDone": []}
    if token:
        fields["pageToken"] = token
    else:
        last_day = _month_start(cursor) - timedelta(days=1)
        fields.update(cursor=_prev_month_key(cursor), pageToken=None)
        if last_day < date.fromisoformat(state["since"]):
            fields["status"] = "done"
    return summary(update(**fields))


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
        if status == 401:
            return "auth"
        if status == 403:
            return _classify_403(exc)
        if status == 429 or status >= 500:
            return "transient"
        return "thread"
    if isinstance(exc, (OSError, TimeoutError, HttpLib2Error)):
        return "transient"
    return "thread"


_RATE_LIMIT_REASONS = frozenset({
    "rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded", "quotaExceeded",
})


def _classify_403(exc) -> str:
    """Gmail uses 403 both for missing permissions (re-auth) and for rate /
    quota limits (transient). Decide by ``error.errors[0].reason``."""
    reason = None
    details = getattr(exc, "error_details", None)
    if isinstance(details, list) and details and isinstance(details[0], dict):
        reason = details[0].get("reason")
    content = getattr(exc, "content", b"") or b""
    if not reason:
        try:
            data = json.loads(content)
            reason = data["error"]["errors"][0]["reason"]
        except (ValueError, TypeError, KeyError, IndexError):
            reason = None
    if reason:
        return "transient" if reason in _RATE_LIMIT_REASONS else "auth"
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    text = f"{exc} {content}".lower()
    return "transient" if ("rate" in text or "quota" in text) else "auth"


def _rejected_status(exc: BaseException) -> int | None:
    """The HTTP status when Gmail rejected a request with a non-auth,
    non-transient 4xx (bad query / page token); else None."""
    from googleapiclient.errors import HttpError  # lazy — heavy

    if not isinstance(exc, HttpError) or _classify(exc) != "thread":
        return None
    status = int(getattr(exc, "status_code", None) or getattr(exc.resp, "status", 0) or 0)
    return status if 400 <= status < 500 else None


def _is_routing_fallback(result) -> bool:
    """True when the pipeline parked the note in needs_review because the
    LLM router failed (router ``method == "fallback"``). Gmail threads always
    have a title, so the router's other fallback (no classifiable content)
    cannot occur here."""
    return (isinstance(result, dict)
            and result.get("method") == "fallback"
            and result.get("context") == "needs_review")


def _import_thread(full, account, existing, denylist, process) -> tuple[str, dict | None]:
    event = _normalize_thread(full, account=account)
    if event is None or _is_denied(event, denylist) or _is_promotional(event):
        return "skipped", None
    if event["id"] in existing:
        return "skipped", None
    result = process(event)
    existing.add(event["id"])
    return "imported", result


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
