"""Joplin connector. Uses the Joplin Data API exposed by the desktop
app's Web Clipper service (default: http://localhost:41184).

Token + Web Clipper service must be enabled in Joplin: Tools → Options →
Web Clipper → "Enable Web Clipper Service", then copy the auth token.
Configure under `joplin:` in `vault/90-meta/routing.yaml`:

    joplin:
      token: "abcdef..."         # required
      host: "http://localhost:41184"   # optional, default shown
      notebooks:                  # optional notebook -> context map
        Sanlam: sanlam
        Personal: personal

Empty `notebooks` map = ingest every notebook (router falls back to LLM /
needs_review). A non-empty map acts as both allowlist and fast-route
table — notes outside listed notebooks are skipped at fetch time so we
don't pay LLM cost on personal scratchpads etc.

Each note surfaces as one event keyed `joplin:note:<note-id>`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from ghostbrain.connectors._base import Connector

log = logging.getLogger("ghostbrain.connectors.joplin")

DEFAULT_HOST = "http://localhost:41184"

NOTE_FIELDS = (
    "id,parent_id,title,body,created_time,updated_time,is_todo,"
    "todo_completed,markup_language,source_url"
)
FOLDER_FIELDS = "id,parent_id,title"

PAGE_SIZE = 100
FIRST_RUN_LOOKBACK_DAYS = 7
HTTP_TIMEOUT_S = 15


class JoplinConnector(Connector):
    """See module docstring."""

    name = "joplin"
    version = "1.0"

    def __init__(
        self,
        config: dict,
        queue_dir: Path,
        state_dir: Path,
        *,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.token: str = str(config.get("token") or "").strip()
        if not self.token:
            raise RuntimeError(
                "joplin.token missing from routing.yaml. Enable Web Clipper "
                "in Joplin and paste the token there."
            )
        self.host: str = (config.get("host") or DEFAULT_HOST).rstrip("/")
        # notebook-name → context. Empty = ingest everything.
        self.notebooks: dict[str, str] = dict(config.get("notebooks") or {})
        self._session = session or requests.Session()

    # ------------------------------------------------------------------
    # Connector contract
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Joplin's `/ping` returns the literal text 'JoplinClipperServer'
        when the service is up. Token is not required for /ping."""
        try:
            r = self._session.get(f"{self.host}/ping", timeout=HTTP_TIMEOUT_S)
        except requests.RequestException as e:
            log.warning("joplin ping failed: %s", e)
            return False
        return r.status_code == 200 and "JoplinClipperServer" in (r.text or "")

    def fetch(self, since: datetime) -> list[dict]:
        # First-run guard: no last_run state → fetch the last week, not all
        # of history.
        floor = datetime.now(timezone.utc) - timedelta(days=FIRST_RUN_LOOKBACK_DAYS)
        if since < floor:
            since = floor
        since_ms = int(since.timestamp() * 1000)

        folders_by_id = self._load_folder_index()
        # If the user configured a notebook allowlist, build the id set up
        # front so we can skip non-listed notebooks before LLM cost.
        allowed_ids: set[str] | None = None
        if self.notebooks:
            wanted = set(self.notebooks.keys())
            allowed_ids = {
                fid for fid, name in folders_by_id.items() if name in wanted
            }
            if not allowed_ids:
                log.warning(
                    "joplin.notebooks set but none matched Joplin folders: %s",
                    sorted(wanted),
                )

        events: list[dict] = []
        for note in self._iter_notes_since(since_ms):
            parent = note.get("parent_id") or ""
            if allowed_ids is not None and parent not in allowed_ids:
                continue
            if not (note.get("body") or "").strip():
                # Title-only notes are common as quick-capture stubs; the
                # pipeline can't route them and they're rarely worth a
                # separate vault note.
                continue
            notebook = folders_by_id.get(parent, "")
            events.append(self._normalize_note(note, notebook=notebook))

        log.info("joplin fetch: %d note(s) since %s", len(events), since.isoformat())
        return events

    def normalize(self, raw: dict) -> dict:
        # `fetch` already returns normalized events. Identity here for
        # contract consistency with the abstract Connector.
        return raw

    # ------------------------------------------------------------------
    # Joplin Data API plumbing
    # ------------------------------------------------------------------

    def _load_folder_index(self) -> dict[str, str]:
        """Return `{folder_id: title}` for every notebook (paginated)."""
        out: dict[str, str] = {}
        page = 1
        while True:
            params = {
                "token": self.token,
                "fields": FOLDER_FIELDS,
                "limit": PAGE_SIZE,
                "page": page,
            }
            data = self._get_json(f"{self.host}/folders?{urlencode(params)}")
            for item in data.get("items") or []:
                fid = item.get("id")
                if fid:
                    out[fid] = item.get("title") or ""
            if not data.get("has_more"):
                break
            page += 1
        return out

    def _iter_notes_since(self, since_ms: int):
        """Yield notes with `updated_time >= since_ms`, oldest first.

        The Data API doesn't support a server-side `updated_time >= N`
        filter, so we order ASC by updated_time and stop walking once we've
        passed the cutoff in both directions (early-out on first page that
        starts after `since_ms` is handled by descending order instead).
        We use DESC so we can break as soon as we hit an older note.
        """
        page = 1
        while True:
            params = {
                "token": self.token,
                "fields": NOTE_FIELDS,
                "order_by": "updated_time",
                "order_dir": "DESC",
                "limit": PAGE_SIZE,
                "page": page,
            }
            data = self._get_json(f"{self.host}/notes?{urlencode(params)}")
            items = data.get("items") or []
            if not items:
                return
            for note in items:
                if int(note.get("updated_time") or 0) < since_ms:
                    return  # everything after this is older too
                yield note
            if not data.get("has_more"):
                return
            page += 1

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            r = self._session.get(url, timeout=HTTP_TIMEOUT_S)
        except requests.RequestException as e:
            log.warning("joplin GET failed: %s", e)
            return {}
        if r.status_code != 200:
            log.warning("joplin GET %s -> HTTP %d: %s",
                        url.split("?", 1)[0], r.status_code, r.text[:200])
            return {}
        try:
            data = r.json()
        except ValueError as e:
            log.warning("joplin response not JSON: %s", e)
            return {}
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def _normalize_note(self, raw: dict, *, notebook: str) -> dict:
        note_id = str(raw.get("id") or "")
        is_todo = bool(raw.get("is_todo"))
        todo_done = bool(raw.get("todo_completed"))
        subtype = "todo" if is_todo else "note"
        if is_todo and todo_done:
            subtype = "todo-done"

        updated_ms = int(raw.get("updated_time") or 0)
        created_ms = int(raw.get("created_time") or 0)
        timestamp = _iso_from_ms(updated_ms or created_ms)

        return {
            "id": f"joplin:note:{note_id}",
            "source": "joplin",
            "type": "note",
            "subtype": subtype,
            "timestamp": timestamp,
            # Joplin is local-only; no remote actor exists.
            "actorId": "joplin:local",
            "title": str(raw.get("title") or "").strip(),
            "body": str(raw.get("body") or "").strip(),
            "url": str(raw.get("source_url") or "").strip(),
            "rawData": {k: raw.get(k) for k in raw if k != "body"},
            "metadata": {
                "noteId": note_id,
                "notebook": notebook,
                "notebookId": raw.get("parent_id") or "",
                "isTodo": is_todo,
                "todoCompleted": todo_done,
                "markupLanguage": raw.get("markup_language"),
                "createdAt": _iso_from_ms(created_ms) if created_ms else None,
                "updatedAt": _iso_from_ms(updated_ms) if updated_ms else None,
            },
        }


def _iso_from_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()
