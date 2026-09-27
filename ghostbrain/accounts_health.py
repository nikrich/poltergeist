"""Per-account connector health — ``<state>/accounts_health.json``.

Keyed ``"<connector>:<account id lower-cased>"`` where connector is the
fetching connector's name (gmail, calendar, outlook_mail, ...). Written by
``for_each_account``, read by the connectors API.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from ghostbrain.paths import state_dir

log = logging.getLogger("ghostbrain.accounts_health")

STATUS_OK = "ok"
STATUS_AUTH = "auth_required"
STATUS_ERROR = "error"

T = TypeVar("T")

_lock = threading.Lock()
_last_run: dict[str, dict[str, str]] = {}


def health_path() -> Path:
    return state_dir() / "accounts_health.json"


def _key(connector: str, account_id: str) -> str:
    return f"{connector}:{account_id.lower()}"


def load_health() -> dict[str, dict]:
    try:
        data = json.loads(health_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("could not read %s (%s); treating as empty", health_path(), e)
        return {}
    return data if isinstance(data, dict) else {}


def health_for(connector: str, account_id: str) -> dict | None:
    return load_health().get(_key(connector, account_id))


def record(connector: str, account_id: str, status: str, error: str | None = None) -> None:
    now = datetime.now(UTC).isoformat()
    with _lock:
        data = load_health()
        key = _key(connector, account_id)
        entry = dict(data.get(key) or {})
        entry["status"] = status
        entry["checkedAt"] = now
        entry["error"] = error
        if status == STATUS_OK:
            entry["lastSuccessAt"] = now
        entry.setdefault("lastSuccessAt", None)
        data[key] = entry
        _write(data)
    _last_run.setdefault(connector, {})[account_id] = status


def _write(data: dict) -> None:
    p = health_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".accounts_health.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def clear_last_run(connector: str) -> None:
    _last_run.pop(connector, None)


def last_run_summary(connector: str) -> dict[str, str]:
    return dict(_last_run.get(connector) or {})


def for_each_account(
    connector: str,
    items: Iterable[T],
    fn: Callable[[T], Iterable[dict]],
    *,
    account_id: Callable[[T], str],
    auth_errors: tuple[type[BaseException], ...] = (),
) -> list[dict]:
    """Run ``fn`` per account, isolating failures. ``auth_errors`` mark the
    account ``auth_required``; any other exception marks it ``error``.
    Returns the events from every account that succeeded."""
    _last_run[connector] = {}
    events: list[dict] = []
    for item in items:
        aid = account_id(item)
        try:
            got = list(fn(item))
        except auth_errors as e:
            log.warning("%s account %s needs re-auth: %s", connector, aid, e)
            record(connector, aid, STATUS_AUTH, str(e))
            continue
        except Exception as e:  # noqa: BLE001 — one account must never stop the rest
            log.warning("%s account %s failed: %s", connector, aid, e)
            record(connector, aid, STATUS_ERROR, str(e))
            continue
        record(connector, aid, STATUS_OK)
        events.extend(got)
    return events
