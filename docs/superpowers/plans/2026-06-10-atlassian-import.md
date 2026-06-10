# Atlassian Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An in-app browser/picker that imports specific Confluence pages and Jira issues into the vault on demand — a new `/v1/import` route family (browse spaces/pages/search/issues + bulk `POST /v1/import` with per-item results, audit events, 409 when unconfigured, max 50 items), a connector refactor that exposes the existing normalize/convert code as reusable functions (with a golden test pinning that scheduled-sync output is byte-identical pre/post refactor), and an import screen with two tabs, checkbox lists, search, a selection bar, and per-item progress/result marks.

**Architecture:** The scheduled sync works like this today (all verified on this branch): `ConfluenceConnector._fetch_site` / `JiraConnector._fetch_site` call `AtlassianClient.get` (`ghostbrain/connectors/atlassian/_base.py` — Basic auth from `ATLASSIAN_EMAIL` + `ATLASSIAN_TOKEN[_<SLUG>]`, 429 backoff, 5xx retries) and normalize each raw payload into the standard event shape (`{id, source, type, subtype, timestamp, actorId, title, body, url, rawData, metadata}`); `Connector.run()` then **enqueues** each event as JSON into `90-meta/queue/pending/`; the worker's `run_loop` (`ghostbrain/worker/main.py`) claims each file and calls `ghostbrain.worker.pipeline.process_event`, which routes (`route_event`: path-first via routing.yaml `confluence.spaces` / `jira.sites`, LLM fallback) and persists via `write_note` (`ghostbrain/worker/note_generator.py`: frontmatter + body to `00-inbox/raw/<source>/` always, and to `20-contexts/<ctx>/confluence/` or `<ctx>/jira/tickets/` when `config.yaml` `worker.routing_mode: live`). The import endpoint skips the queue hop and calls `process_event` **inline** on the same normalized event — identical frontmatter, body, filename, and routing-fallback behaviour, one (path-routed, so usually zero-LLM) call per item. Task 1 extracts the connectors' embedded normalize functions (`normalize_page`, `page_url`, `normalize_issue`, `MY_ISSUES_JQL`, `PAGE_EXPAND`) to module level with delegating call sites and a golden characterization test committed *before* the refactor. Tasks 2–4 add `ghostbrain/api/repo/import_atlassian.py` (browse + `import_items`) and `ghostbrain/api/routes/import_atlassian.py`. Tasks 5–6 add the desktop types/hooks (`ApiError` with HTTP status surfaces the 409) and the `'import'` screen. Tasks 7–8 are the regression gate and a real-credentials manual E2E.

**One hard codebase fact the spec got wrong (drives the dedup design):** `write_note._filename_for` builds `{ts_slug}-{title_slug}-{id_suffix}.md` where `ts_slug` comes from the event **timestamp** (the page's `version.when` / issue's `updated`) and `id_suffix` is the first 12 chars of the slugified note id — which for Confluence is always the degenerate `confluencesf` and for Jira `jirasft…` (verified against real vault files like `20260507T081447-mvp-wrap-up-checklist…-confluencesf.md`). So the naming is deterministic **per content version**, not per pageId/key: re-importing an *unchanged* item overwrites the same file, but re-importing a *changed* item lands at a new filename. To honor the spec's "re-importing updates the same note", `import_items` looks up existing notes by frontmatter `id` (the stable `confluence:<slug>:<pageId>` / `jira:<slug>:<KEY>`) before processing, deletes any stale copies the new write didn't overwrite, and reports `updated: true` whenever a prior copy existed.

**Tech Stack:** Python 3.11 + FastAPI (sidecar), pytest (`ghostbrain/api/tests/` with `tmp_vault`/`client`/`auth_headers` fixtures; connector golden tests in `tests/` with its `vault` fixture), Electron + React + TypeScript (desktop), Zustand (toast/navigation stores), React Query (data), Vitest + React Testing Library (renderer tests).

**Spec:** `docs/superpowers/specs/2026-06-10-atlassian-import-design.md`

**Verified baselines (2026-06-10, this worktree, after the activity-heatmap merge):**

- Backend: `/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/ -q` → **57 passed** (run from the worktree root).
- Connector/worker suites: `… -m pytest tests/test_confluence_connector.py tests/test_jira_connector.py tests/test_pipeline.py -q` → **12 passed** (5 + 4 + 3).
- Desktop: `cd desktop && npx vitest run` → **37 passed** (9 files). `cd desktop && npm run typecheck` → clean.
- Real `~/ghostbrain/vault/90-meta/routing.yaml` shape: `jira.sites` is a **dict** `{sft.atlassian.net: sanlam}`; `confluence.sites` dict `{sft.atlassian.net: sanlam}`; `confluence.spaces` dict `{DIG: sanlam, SFTHome: sanlam, SPE: sanlam}`. The runners call `list(...)` on these (dict → keys). Real `config.yaml` has `worker.routing_mode: live`.
- The forwarder (`desktop/src/main/api-forwarder.ts`) already returns `{ ok: false, error: <FastAPI detail>, status: <HTTP code> }`, but `desktop/src/renderer/lib/api/client.ts` currently throws a plain `Error` and **drops the status** — Task 5 adds an `ApiError` carrying it (needed for the 409 call-to-action).
- There is **no house tab component**; the closest pattern is the capture screen's chip strip (`chipClass` in `desktop/src/renderer/screens/capture.tsx`). The import screen's tabs reuse that styling.
- `Lucide` resolves kebab names; `download`, `chevron-down`, `chevron-right`, `plug`, `search` all exist in lucide-react.

**Deliberate decisions (read before implementing):**

1. **Import persists via `pipeline.process_event` inline**, not by re-implementing write logic and not via the worker queue (waiting on the worker poll loop would make the endpoint unreliable and the worker may not even be running). `process_event` is exactly what the worker calls on dequeued connector events, so the written note is identical to a synced one. The worker's `event_processed` audit line is written by `run_loop`, **not** by `process_event`, so the import path writes its own `import_completed` audit line without double-logging.
2. **Dedup by frontmatter `id` + stale-file removal** (see the codebase-fact paragraph above). `updated: true` ⇔ a note with the same event id already existed anywhere in `00-inbox/raw/<source>/` or `20-contexts/*/<source-dir>/`.
3. **`GET /v1/import/confluence/pages` returns `{items, nextCursor}`** rather than the spec table's bare array — the spec itself declares a `cursor` query param, and Confluence v1 paging is start/limit, so the cursor is the stringified next start offset. The other three browse endpoints return bare arrays as specced.
4. **Per-item UI progress via sequential 1-item POSTs.** The endpoint accepts up to 50 items per request (batch semantics for non-interactive callers, 422 above 50), but a single bulk POST can't stream progress. `useImportItems` loops `POST /v1/import {items:[item]}` one at a time, firing an `onItem` callback before each — that is what renders "3/7 — importing PAS-1234…" truthfully.
5. **Both "no sites/spaces configured" and "auth env vars missing" normalize to `ImportNotConfiguredError`** with the spec's exact detail string (`"confluence connector not configured — run onboarding"` / jira equivalent), and every route maps that to 409. `auth_for_site` only reads env vars (no network), so the POST validates config+auth up front and 409s before touching any item.
6. **Space display names are best-effort**: one `GET /wiki/rest/api/space?spaceKey=…` per site, falling back to the key when the lookup fails — browse must work even if that cosmetic call breaks.
7. **Import browse queries use `retry: false`** so a 409 renders the call-to-action immediately instead of after three retries.
8. Tests never touch real config: routing.yaml/config.yaml fixtures are written into `tmp_vault`, and `AtlassianClient`/`auth_for_site` are monkeypatched **at the import-repo module namespace** (`ghostbrain.api.repo.import_atlassian.*`), the same patch-where-it's-used style as `tests/test_confluence_connector.py` patching `ghostbrain.connectors.confluence.AtlassianClient.get`.

---

## Task 1: Connector refactor — extract reusable normalize functions (golden-pinned, zero behaviour change)

**Files:**
- Test: `tests/test_atlassian_import_refactor.py` (create — committed BEFORE the refactor)
- Modify: `ghostbrain/connectors/confluence/__init__.py`
- Modify: `ghostbrain/connectors/jira/__init__.py`

- [ ] **Step 1: Write the golden characterization test (it must PASS against current code)**

Create `tests/test_atlassian_import_refactor.py`:

```python
"""Refactor-safety net for the Atlassian import feature.

The import endpoints reuse the confluence/jira conversion code, which Task 1
extracts from the connector classes into module-level functions. These golden
tests pin the scheduled-sync output EXACTLY (full-dict equality) so the
extraction cannot change connector behaviour. They are written and committed
BEFORE the refactor and must stay green, unmodified, after it.

If the body literal below mismatches on the first run (markdownify whitespace),
print the actual event and adjust the literal NOW — before the refactor —
never after.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

PAGE_RAW = {
    "id": "1234567",
    "title": "ASCP architecture overview",
    "space": {"key": "DIG"},
    "version": {
        "number": 5,
        "when": "2026-05-07T09:30:00.000Z",
        "by": {"accountId": "u1", "displayName": "Jannik"},
    },
    "body": {
        "storage": {
            "value": "<p>This is the <strong>ASCP</strong> overview.</p>"
                     "<p>It describes <em>microservices</em> and BFFs.</p>",
        },
    },
    "_links": {
        "base": "https://sft.atlassian.net/wiki",
        "webui": "/spaces/DIG/pages/1234567/Overview",
    },
}

EXPECTED_PAGE_EVENT = {
    "id": "confluence:sft:1234567",
    "source": "confluence",
    "type": "page",
    "subtype": "updated",
    "timestamp": "2026-05-07T09:30:00.000Z",
    "actorId": "confluence:u1",
    "title": "ASCP architecture overview",
    "body": "This is the **ASCP** overview.\n\nIt describes *microservices* and BFFs.",
    "url": "https://sft.atlassian.net/wiki/spaces/DIG/pages/1234567/Overview",
    "rawData": PAGE_RAW,
    "metadata": {
        "site": "sft.atlassian.net",
        "siteSlug": "sft",
        "space": "DIG",
        "pageId": "1234567",
        "version": 5,
        "lastModifiedBy": "Jannik",
    },
}

ISSUE_RAW = {
    "key": "DIGISURE-1234",
    "id": "10001",
    "fields": {
        "summary": "Add cashback to quote domain",
        "status": {"name": "In Progress",
                   "statusCategory": {"key": "indeterminate"}},
        "priority": {"name": "Medium"},
        "issuetype": {"name": "Story"},
        "assignee": {"accountId": "abc", "displayName": "Jannik"},
        "reporter": {"accountId": "def", "displayName": "Reporter"},
        "labels": ["capstone"],
        "project": {"key": "DIGISURE"},
        "created": "2026-05-01T08:00:00.000+0000",
        "updated": "2026-05-07T10:00:00.000+0000",
        "description": {
            "type": "doc",
            "content": [{
                "type": "paragraph",
                "content": [{"type": "text", "text": "Add a cashback field..."}],
            }],
        },
    },
}

EXPECTED_ISSUE_EVENT = {
    "id": "jira:sft:DIGISURE-1234",
    "source": "jira",
    "type": "ticket",
    "subtype": "in progress",
    "timestamp": "2026-05-07T10:00:00.000+0000",
    "actorId": "jira:def",
    "title": "DIGISURE-1234 Add cashback to quote domain",
    "body": "Add a cashback field...",
    "url": "https://sft.atlassian.net/browse/DIGISURE-1234",
    "rawData": ISSUE_RAW,
    "metadata": {
        "site": "sft.atlassian.net",
        "siteSlug": "sft",
        "project": "DIGISURE",
        "key": "DIGISURE-1234",
        "status": "In Progress",
        "statusCategory": "indeterminate",
        "priority": "Medium",
        "assignee": "Jannik",
        "reporter": "Reporter",
        "labels": ["capstone"],
        "issueType": "Story",
    },
}


@pytest.fixture(autouse=True)
def _atlassian_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
    monkeypatch.setenv("ATLASSIAN_TOKEN_SFT", "test-token")


def test_confluence_scheduled_sync_output_is_pinned(tmp_path) -> None:
    from ghostbrain.connectors.confluence import ConfluenceConnector

    connector = ConfluenceConnector(
        config={"sites": ["sft.atlassian.net"], "spaces": {"DIG": "sanlam"}},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
    )
    with patch(
        "ghostbrain.connectors.confluence.AtlassianClient.get",
        return_value={"results": [PAGE_RAW]},
    ):
        events = connector.fetch(datetime(2026, 5, 6, tzinfo=timezone.utc))
    assert events == [EXPECTED_PAGE_EVENT]


def test_jira_scheduled_sync_output_is_pinned(tmp_path) -> None:
    from ghostbrain.connectors.jira import JiraConnector

    connector = JiraConnector(
        config={"sites": ["sft.atlassian.net"]},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
    )
    with patch(
        "ghostbrain.connectors.jira.AtlassianClient.get",
        return_value={"issues": [ISSUE_RAW]},
    ):
        events = connector.fetch(datetime(2026, 5, 1, tzinfo=timezone.utc))
    assert events == [EXPECTED_ISSUE_EVENT]
```

- [ ] **Step 2: Run it — it must PASS against the unrefactored code**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest tests/test_atlassian_import_refactor.py -v
```
Expected: **2 passed**. If the `body` literal mismatches (markdownify whitespace), pin the actual output into the literal and re-run until green — this is a characterization test of *current* behaviour.

- [ ] **Step 3: Commit the golden test by itself**

```bash
git add tests/test_atlassian_import_refactor.py
git commit -m "test(connectors): golden tests pinning confluence/jira sync output pre-refactor"
```

- [ ] **Step 4: Refactor the Confluence connector**

Replace `ghostbrain/connectors/confluence/__init__.py` with:

```python
"""Confluence Cloud connector. Fetches pages updated in monitored spaces
within the last day.

``normalize_page``, ``page_url``, ``_strip_html``, and ``PAGE_EXPAND`` are
module-level so the import endpoints (ghostbrain/api/repo/import_atlassian.py)
reuse the exact scheduled-sync conversion."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.atlassian._base import (
    AtlassianAuthError,
    AtlassianClient,
    auth_for_site,
    slug_for_host,
)

log = logging.getLogger("ghostbrain.connectors.confluence")

FIRST_RUN_LOOKBACK_HOURS = 24
WINDOW_OVERLAP_HOURS = 2
MAX_RESULTS = 25
# Expansions required by normalize_page; shared with the import endpoints.
PAGE_EXPAND = "body.storage,version,space,history"
BODY_TRUNCATE_CHARS = 5000


class ConfluenceConnector(Connector):
    name = "confluence"
    version = "1.0"

    def __init__(
        self,
        config: dict,
        queue_dir: Path,
        state_dir: Path,
    ) -> None:
        super().__init__(config, queue_dir, state_dir)
        # config["spaces"] is a dict of {space_key: context}.
        self.space_map: dict[str, str] = dict(config.get("spaces") or {})
        # config["sites"] is a list of hosts. Each site uses its own auth.
        self.sites: list[str] = list(config.get("sites") or [])
        self.lookback_hours = int(config.get("lookback_hours") or 24)

    def health_check(self) -> bool:
        if not self.sites:
            return False
        try:
            for host in self.sites:
                email, token = auth_for_site(host)
                client = AtlassianClient(host, email, token)
                client.get("/wiki/rest/api/user/current")
        except (AtlassianAuthError, Exception) as e:
            log.warning("confluence health check failed: %s", e)
            return False
        return True

    def fetch(self, since: datetime) -> list[dict]:
        if not self.sites or not self.space_map:
            log.info("no confluence sites/spaces configured; skipping fetch")
            return []

        floor = datetime.now(timezone.utc) - timedelta(hours=FIRST_RUN_LOOKBACK_HOURS)
        if since < floor:
            since = floor
        since = since - timedelta(hours=WINDOW_OVERLAP_HOURS)

        events: list[dict] = []
        for host in self.sites:
            try:
                events.extend(self._fetch_site(host, since))
            except AtlassianAuthError as e:
                log.warning("skipping %s: %s", host, e)
            except Exception as e:  # noqa: BLE001
                log.exception("confluence fetch failed for %s: %s", host, e)
        log.info("confluence fetch: %d page(s) across %d site(s)",
                 len(events), len(self.sites))
        return events

    def normalize(self, raw: dict) -> dict:
        return raw

    # ------------------------------------------------------------------
    # Per-site fetch
    # ------------------------------------------------------------------

    def _fetch_site(self, host: str, since: datetime) -> Iterable[dict]:
        email, token = auth_for_site(host)
        client = AtlassianClient(host, email, token)

        # CQL date format: yyyy-MM-dd HH:mm
        since_str = since.strftime("%Y-%m-%d %H:%M")
        space_keys = list(self.space_map.keys())
        # Build "space = X OR space = Y OR ..."
        space_clause = " OR ".join(f'space = "{k}"' for k in space_keys)
        cql = (
            f'type = page AND ({space_clause}) AND lastModified >= "{since_str}"'
        )

        params = {
            "cql": cql,
            "expand": PAGE_EXPAND,
            "limit": MAX_RESULTS,
        }
        data = client.get("/wiki/rest/api/content/search", params=params)
        results = data.get("results", []) or []
        for page in results:
            ev = normalize_page(page, host=host, space_map=self.space_map)
            if ev is not None:
                yield ev


def normalize_page(raw: dict, *, host: str, space_map: dict[str, str]) -> dict | None:
    """Normalize one raw Confluence page into the standard event shape.

    Module-level (rather than a connector method) so the import endpoints
    run the exact conversion the scheduled sync runs. Returns None for pages
    without an id or in a space outside ``space_map``.
    """
    page_id = raw.get("id")
    if not page_id:
        return None
    title = (raw.get("title") or "").strip()
    space = (raw.get("space") or {}).get("key", "")
    if space and space not in space_map:
        return None  # space not in our routing — skip

    version = (raw.get("version") or {})
    last_modified = version.get("when") or raw.get("lastModified")

    body_html = ((raw.get("body") or {}).get("storage") or {}).get("value", "")
    body_text = _strip_html(body_html)
    # Truncate aggressively — pages can be huge.
    if len(body_text) > BODY_TRUNCATE_CHARS:
        body_text = body_text[:BODY_TRUNCATE_CHARS] + "\n\n[…truncated]"

    url = page_url(host, raw)
    site_slug = slug_for_host(host)

    return {
        "id": f"confluence:{site_slug}:{page_id}",
        "source": "confluence",
        "type": "page",
        "subtype": "updated",
        "timestamp": last_modified or _now_iso(),
        "actorId": f"confluence:{(version.get('by') or {}).get('accountId', '?')}",
        "title": title,
        "body": body_text,
        "url": url,
        "rawData": raw,
        "metadata": {
            "site": host,
            "siteSlug": site_slug,
            "space": space,
            "pageId": page_id,
            "version": version.get("number"),
            "lastModifiedBy": (version.get("by") or {}).get("displayName"),
        },
    }


def page_url(host: str, raw: dict) -> str:
    links = raw.get("_links") or {}
    webui = links.get("webui")
    if webui:
        base = links.get("base") or f"https://{host}/wiki"
        return base.rstrip("/") + webui
    page_id = raw.get("id", "")
    return f"https://{host}/wiki/spaces/{((raw.get('space') or {}).get('key') or '')}/pages/{page_id}"


_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _strip_html(html: str) -> str:
    """Confluence storage format (XHTML-ish) → markdown.

    Uses markdownify so paragraph breaks, headings, lists, and tables survive
    the round-trip. The previous regex-strip flattened everything into a
    single line.
    """
    if not html:
        return ""
    from markdownify import markdownify

    text = markdownify(
        html,
        heading_style="ATX",         # `#` headings, not underline
        bullets="-",                  # `- ` instead of `* `
        strip=["script", "style"],
    )
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```

(Diff vs current code: the `_normalize_page`/`_page_url` **methods** become module-level `normalize_page`/`page_url` with `space_map` as an explicit kwarg; `_fetch_site` calls the function and uses the new `PAGE_EXPAND` constant; the unused `typing.Any` import is dropped; the truncation threshold becomes the `BODY_TRUNCATE_CHARS` constant. No logic changes.)

- [ ] **Step 5: Refactor the Jira connector**

Replace `ghostbrain/connectors/jira/__init__.py` with:

```python
"""Jira Cloud connector. Fetches tickets the user is involved in
(assignee, reporter, watcher) that have been updated recently.

``normalize_issue``, ``_adf_to_text``, ``MY_ISSUES_JQL``, and ``JQL_FIELDS``
are module-level so the import endpoints (ghostbrain/api/repo/
import_atlassian.py) reuse the exact scheduled-sync conversion."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.atlassian._base import (
    AtlassianAuthError,
    AtlassianClient,
    auth_for_site,
    slug_for_host,
)

log = logging.getLogger("ghostbrain.connectors.jira")

# How far back to look on first run (no last_run state file yet).
FIRST_RUN_LOOKBACK_HOURS = 24
# Buffer added to last_run window so an event updated right before the
# previous fetch isn't missed.
WINDOW_OVERLAP_HOURS = 1
# Cap per-site fetch.
MAX_RESULTS = 50

JQL_FIELDS = (
    "summary,status,assignee,reporter,priority,issuetype,labels,project,"
    "created,updated,description,resolution"
)

# The connector's "my issues" clause; the import browse list reuses it.
MY_ISSUES_JQL = (
    "(assignee = currentUser() OR reporter = currentUser() "
    "OR watcher = currentUser())"
)


class JiraConnector(Connector):
    """One connector instance, multiple sites — runs through each site
    sequentially. Each site uses its own auth pair from the env."""

    name = "jira"
    version = "1.0"

    def __init__(
        self,
        config: dict,
        queue_dir: Path,
        state_dir: Path,
    ) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.sites: list[str] = list(config.get("sites") or [])
        self.lookback_hours = int(config.get("lookback_hours") or 4)

    def health_check(self) -> bool:
        if not self.sites:
            return False
        try:
            for host in self.sites:
                email, token = auth_for_site(host)
                client = AtlassianClient(host, email, token)
                client.get("/rest/api/3/myself")
        except (AtlassianAuthError, Exception) as e:
            log.warning("jira health check failed: %s", e)
            return False
        return True

    def fetch(self, since: datetime) -> list[dict]:
        if not self.sites:
            log.info("no jira sites configured; skipping fetch")
            return []

        floor = datetime.now(timezone.utc) - timedelta(hours=FIRST_RUN_LOOKBACK_HOURS)
        if since < floor:
            since = floor
        # Apply overlap buffer in case events came in just before the last run.
        since = since - timedelta(hours=WINDOW_OVERLAP_HOURS)

        events: list[dict] = []
        for host in self.sites:
            try:
                events.extend(self._fetch_site(host, since))
            except AtlassianAuthError as e:
                log.warning("skipping %s: %s", host, e)
            except Exception as e:  # noqa: BLE001
                log.exception("jira fetch failed for %s: %s", host, e)
        log.info("jira fetch: %d event(s) across %d site(s)",
                 len(events), len(self.sites))
        return events

    def normalize(self, raw: dict) -> dict:
        # `_fetch_site` already produces normalized events.
        return raw

    # ------------------------------------------------------------------
    # Per-site fetch
    # ------------------------------------------------------------------

    def _fetch_site(self, host: str, since: datetime) -> Iterable[dict]:
        email, token = auth_for_site(host)
        client = AtlassianClient(host, email, token)

        # Atlassian's JQL date format wants "yyyy-MM-dd HH:mm".
        since_str = since.strftime("%Y-%m-%d %H:%M")
        jql = f'{MY_ISSUES_JQL} AND updated >= "{since_str}"'

        # Atlassian recommends /search/jql (token-paginated) but the classic
        # /search still works on Cloud. We use the new endpoint.
        params = {
            "jql": jql,
            "fields": JQL_FIELDS,
            "maxResults": MAX_RESULTS,
        }
        try:
            data = client.get("/rest/api/3/search/jql", params=params)
        except Exception as e:  # noqa: BLE001
            # Fall back to legacy endpoint if the new one is blocked.
            log.info("falling back to legacy /search for %s: %s", host, e)
            data = client.get("/rest/api/3/search", params=params)

        issues = data.get("issues", []) or []
        for issue in issues:
            yield normalize_issue(issue, host=host)


def normalize_issue(raw: dict, *, host: str) -> dict:
    """Normalize one raw Jira issue into the standard event shape.

    Module-level (rather than a connector method) so the import endpoints
    run the exact conversion the scheduled sync runs.
    """
    fields = raw.get("fields") or {}
    key = raw.get("key", "?")
    summary = (fields.get("summary") or "").strip()
    status_obj = fields.get("status") or {}
    priority_obj = fields.get("priority") or {}
    assignee_obj = fields.get("assignee") or {}
    reporter_obj = fields.get("reporter") or {}
    project = (fields.get("project") or {}).get("key", "")

    site_slug = slug_for_host(host)

    return {
        "id": f"jira:{site_slug}:{key}",
        "source": "jira",
        "type": "ticket",
        "subtype": (status_obj.get("name") or "").lower() or "open",
        "timestamp": fields.get("updated") or fields.get("created") or _now_iso(),
        "actorId": f"jira:{(reporter_obj or {}).get('accountId', '?')}",
        "title": f"{key} {summary}".strip(),
        "body": _adf_to_text(fields.get("description")) or "",
        "url": f"https://{host}/browse/{key}",
        "rawData": raw,
        "metadata": {
            "site": host,
            "siteSlug": site_slug,
            "project": project,
            "key": key,
            "status": status_obj.get("name"),
            "statusCategory": (status_obj.get("statusCategory") or {}).get("key"),
            "priority": priority_obj.get("name"),
            "assignee": (assignee_obj or {}).get("displayName"),
            "reporter": (reporter_obj or {}).get("displayName"),
            "labels": fields.get("labels") or [],
            "issueType": ((fields.get("issuetype") or {}) or {}).get("name"),
        },
    }


def _adf_to_text(adf: Any) -> str:
    """Flatten an Atlassian Document Format value to plain text.

    Jira returns rich-text descriptions in ADF. Full conversion is non-
    trivial; we just walk the tree and concatenate text leaves so the
    extractor / digest get something readable.
    """
    if adf is None:
        return ""
    if isinstance(adf, str):
        return adf
    if isinstance(adf, dict):
        if adf.get("type") == "text" and isinstance(adf.get("text"), str):
            return adf["text"]
        children = adf.get("content") or []
        return "".join(_adf_to_text(c) for c in children)
    if isinstance(adf, list):
        return "\n".join(_adf_to_text(c) for c in adf)
    return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```

(Diff vs current code: `_normalize_issue` method → module-level `normalize_issue`; the JQL clause becomes the `MY_ISSUES_JQL` constant interpolated identically. No logic changes.)

- [ ] **Step 6: Append the equivalence tests to the golden file**

Append to `tests/test_atlassian_import_refactor.py`:

```python
def test_normalize_page_function_matches_pinned_output() -> None:
    from ghostbrain.connectors.confluence import normalize_page

    assert normalize_page(
        PAGE_RAW, host="sft.atlassian.net", space_map={"DIG": "sanlam"}
    ) == EXPECTED_PAGE_EVENT


def test_normalize_page_drops_unmonitored_space() -> None:
    from ghostbrain.connectors.confluence import normalize_page

    assert normalize_page(
        PAGE_RAW, host="sft.atlassian.net", space_map={"OTHER": "personal"}
    ) is None


def test_normalize_issue_function_matches_pinned_output() -> None:
    from ghostbrain.connectors.jira import normalize_issue

    assert normalize_issue(ISSUE_RAW, host="sft.atlassian.net") == EXPECTED_ISSUE_EVENT
```

- [ ] **Step 7: Run the golden file + the existing connector suites**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest \
  tests/test_atlassian_import_refactor.py \
  tests/test_confluence_connector.py tests/test_jira_connector.py tests/test_pipeline.py -v
```
Expected: **17 passed** (5 golden + 5 confluence + 4 jira + 3 pipeline). The two pinned tests pass **unmodified** — that is the refactor-safety guarantee.

Also confirm the API suite is untouched:
```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/ -q
```
Expected: **57 passed**.

- [ ] **Step 8: Commit**

```bash
git add ghostbrain/connectors/confluence/__init__.py \
        ghostbrain/connectors/jira/__init__.py \
        tests/test_atlassian_import_refactor.py
git commit -m "refactor(connectors): extract normalize_page/normalize_issue to module level (golden-pinned)"
```

---

## Task 2: Import repo — browse functions + config detection (+ shared test fixtures)

**Files:**
- Create: `ghostbrain/api/models/import_atlassian.py`
- Create: `ghostbrain/api/repo/import_atlassian.py` (browse half; `import_items` lands in Task 3)
- Modify: `ghostbrain/api/tests/conftest.py` (add `fake_atlassian` fixture + routing/config helpers)
- Test: `ghostbrain/api/tests/test_import_repo.py` (create)

- [ ] **Step 1: Add the shared fixtures to `ghostbrain/api/tests/conftest.py`**

Two edits. First, add `yaml` to the imports at the top (after `import os`):

```python
import yaml
```

Then append at the end of the file:

```python
def write_import_routing(vault: Path, *, jira: bool = True, confluence: bool = True) -> Path:
    """Write a routing.yaml mirroring the real shape: dicts keyed by host/space."""
    routing: dict = {"version": 1}
    if jira:
        routing["jira"] = {"sites": {"sft.atlassian.net": "sanlam"}}
    if confluence:
        routing["confluence"] = {
            "sites": {"sft.atlassian.net": "sanlam"},
            "spaces": {"DIG": "sanlam", "SPE": "sanlam"},
        }
    p = vault / "90-meta" / "routing.yaml"
    p.write_text(yaml.safe_dump(routing))
    return p


def write_live_config(vault: Path) -> Path:
    """routing_mode live so write_note also writes the context copy."""
    p = vault / "90-meta" / "config.yaml"
    p.write_text(yaml.safe_dump({"worker": {"routing_mode": "live"}}))
    return p


@pytest.fixture
def fake_atlassian(monkeypatch: pytest.MonkeyPatch):
    """Replace AtlassianClient + auth_for_site in the import-repo namespace.

    Register URL-path prefixes on ``registry.routes`` (payload dict, or a
    callable ``(path, params) -> dict`` that may raise); the longest matching
    prefix wins. Every GET is recorded on ``registry.calls`` as
    ``(host, path, params)``.
    """
    from ghostbrain.api.repo import import_atlassian as repo

    class Registry:
        def __init__(self) -> None:
            self.routes: dict[str, object] = {}
            self.calls: list[tuple[str, str, dict | None]] = []

    registry = Registry()

    class FakeClient:
        def __init__(self, host: str, email: str, token: str) -> None:
            self.host = host

        def get(self, path: str, params: dict | None = None, **_kw) -> dict:
            registry.calls.append((self.host, path, params))
            match = max(
                (p for p in registry.routes if path.startswith(p)),
                key=len,
                default=None,
            )
            if match is None:
                raise AssertionError(f"unexpected atlassian GET {path}")
            payload = registry.routes[match]
            return payload(path, params) if callable(payload) else payload  # type: ignore[operator]

    monkeypatch.setattr(repo, "AtlassianClient", FakeClient)
    monkeypatch.setattr(repo, "auth_for_site", lambda host: ("u@example.com", "tok"))
    return registry
```

- [ ] **Step 2: Write the failing repo test**

Create `ghostbrain/api/tests/test_import_repo.py`:

```python
"""Browse half of the import repo: spaces, pages, search, jira issues,
and the 409 (not-configured) detection. AtlassianClient is faked via the
conftest `fake_atlassian` registry."""
from pathlib import Path

import pytest

from ghostbrain.api.tests.conftest import write_import_routing

PAGE_LIST_ITEM = {
    "id": "100",
    "title": "ASCP architecture",
    "version": {"number": 4, "when": "2026-06-01T10:00:00.000Z"},
    "children": {"page": {"size": 2}},
}
PAGE_LIST_LEAF = {
    "id": "200",
    "title": "Runbooks",
    "version": {"number": 1, "when": "2026-05-20T08:00:00.000Z"},
    "children": {"page": {"size": 0}},
}
SEARCH_HIT = {
    "id": "300",
    "title": "Quote domain design",
    "space": {"key": "SPE"},
    "version": {"number": 7, "when": "2026-04-01T09:00:00.000Z"},
    "children": {"page": {"size": 0}},
}
ISSUE_LIST_ITEM = {
    "key": "DIGISURE-1",
    "fields": {
        "summary": "Fix the BFF",
        "status": {"name": "In Progress"},
        "project": {"key": "DIGISURE"},
        "updated": "2026-06-08T10:00:00.000+0000",
    },
}


def test_list_spaces_returns_monitored_spaces_with_names(
    tmp_vault: Path, fake_atlassian
):
    from ghostbrain.api.repo.import_atlassian import list_spaces

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/space"] = {
        "results": [
            {"key": "DIG", "name": "Digisure"},
            {"key": "SPE", "name": "Short-term"},
        ]
    }
    rows = list_spaces()
    assert rows == [
        {"site": "sft.atlassian.net", "siteSlug": "sft", "key": "DIG",
         "name": "Digisure", "context": "sanlam"},
        {"site": "sft.atlassian.net", "siteSlug": "sft", "key": "SPE",
         "name": "Short-term", "context": "sanlam"},
    ]


def test_list_spaces_falls_back_to_key_when_name_lookup_fails(
    tmp_vault: Path, fake_atlassian
):
    from ghostbrain.api.repo.import_atlassian import list_spaces

    write_import_routing(tmp_vault)

    def boom(path, params):
        raise RuntimeError("confluence is down")

    fake_atlassian.routes["/wiki/rest/api/space"] = boom
    rows = list_spaces()
    assert [r["name"] for r in rows] == ["DIG", "SPE"]


def test_list_spaces_raises_when_unconfigured(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import (
        CONFLUENCE_NOT_CONFIGURED,
        ImportNotConfiguredError,
        list_spaces,
    )

    # no routing.yaml at all
    with pytest.raises(ImportNotConfiguredError) as exc:
        list_spaces()
    assert str(exc.value) == CONFLUENCE_NOT_CONFIGURED


def test_list_spaces_raises_when_auth_missing(
    tmp_vault: Path, fake_atlassian, monkeypatch: pytest.MonkeyPatch
):
    from ghostbrain.api.repo import import_atlassian as repo
    from ghostbrain.connectors.atlassian._base import AtlassianAuthError

    write_import_routing(tmp_vault)

    def no_auth(host):
        raise AtlassianAuthError("ATLASSIAN_EMAIL not set")

    monkeypatch.setattr(repo, "auth_for_site", no_auth)
    with pytest.raises(repo.ImportNotConfiguredError) as exc:
        repo.list_spaces()
    assert str(exc.value) == repo.CONFLUENCE_NOT_CONFIGURED


def test_list_pages_top_level_uses_root_depth(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import list_confluence_pages

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/space/DIG/content/page"] = {
        "results": [PAGE_LIST_ITEM, PAGE_LIST_LEAF]
    }
    page = list_confluence_pages(site="sft.atlassian.net", space="DIG")
    assert page["items"] == [
        {"site": "sft.atlassian.net", "id": "100", "title": "ASCP architecture",
         "parentId": None, "hasChildren": True,
         "updatedAt": "2026-06-01T10:00:00.000Z", "version": 4, "space": "DIG"},
        {"site": "sft.atlassian.net", "id": "200", "title": "Runbooks",
         "parentId": None, "hasChildren": False,
         "updatedAt": "2026-05-20T08:00:00.000Z", "version": 1, "space": "DIG"},
    ]
    assert page["nextCursor"] is None  # fewer results than the limit
    host, path, params = fake_atlassian.calls[-1]
    assert params["depth"] == "root"
    assert params["start"] == 0
    assert "children.page" in params["expand"]


def test_list_pages_children_with_cursor(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import list_confluence_pages

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/content/100/child/page"] = {
        "results": [PAGE_LIST_ITEM, PAGE_LIST_LEAF]
    }
    page = list_confluence_pages(
        site="sft.atlassian.net", space="DIG", parent="100", limit=2, cursor="4"
    )
    assert [i["parentId"] for i in page["items"]] == ["100", "100"]
    # limit hit → there may be more; nextCursor advances start by limit.
    assert page["nextCursor"] == "6"
    host, path, params = fake_atlassian.calls[-1]
    assert path == "/wiki/rest/api/content/100/child/page"
    assert params["start"] == 4
    assert params["limit"] == 2


def test_list_pages_rejects_unknown_site_or_space(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import list_confluence_pages

    write_import_routing(tmp_vault)
    with pytest.raises(ValueError):
        list_confluence_pages(site="evil.atlassian.net", space="DIG")
    with pytest.raises(ValueError):
        list_confluence_pages(site="sft.atlassian.net", space="NOTMONITORED")


def test_search_confluence_builds_title_cql_across_spaces(
    tmp_vault: Path, fake_atlassian
):
    from ghostbrain.api.repo.import_atlassian import search_confluence

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/content/search"] = {
        "results": [SEARCH_HIT]
    }
    rows = search_confluence(q='quote "domain"')
    assert rows == [
        {"site": "sft.atlassian.net", "id": "300", "title": "Quote domain design",
         "parentId": None, "hasChildren": False,
         "updatedAt": "2026-04-01T09:00:00.000Z", "version": 7, "space": "SPE"},
    ]
    host, path, params = fake_atlassian.calls[-1]
    cql = params["cql"]
    assert 'type = page' in cql
    assert 'space = "DIG"' in cql and 'space = "SPE"' in cql
    assert 'title ~ "quote \\"domain\\""' in cql


def test_jira_issues_default_my_issues_jql(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import list_jira_issues
    from ghostbrain.connectors.jira import MY_ISSUES_JQL

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/rest/api/3/search/jql"] = {"issues": [ISSUE_LIST_ITEM]}
    rows = list_jira_issues()
    assert rows == [
        {"site": "sft.atlassian.net", "key": "DIGISURE-1", "summary": "Fix the BFF",
         "status": "In Progress", "project": "DIGISURE",
         "updatedAt": "2026-06-08T10:00:00.000+0000"},
    ]
    host, path, params = fake_atlassian.calls[-1]
    assert params["jql"] == f"{MY_ISSUES_JQL} ORDER BY updated DESC"


def test_jira_issues_text_search(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import list_jira_issues

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/rest/api/3/search/jql"] = {"issues": [ISSUE_LIST_ITEM]}
    list_jira_issues(q="cashback")
    host, path, params = fake_atlassian.calls[-1]
    assert params["jql"] == 'text ~ "cashback" ORDER BY updated DESC'


def test_jira_issues_raises_when_unconfigured(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import (
        JIRA_NOT_CONFIGURED,
        ImportNotConfiguredError,
        list_jira_issues,
    )

    write_import_routing(tmp_vault, jira=False)  # confluence only
    with pytest.raises(ImportNotConfiguredError) as exc:
        list_jira_issues()
    assert str(exc.value) == JIRA_NOT_CONFIGURED
```

- [ ] **Step 3: Run test to verify it fails**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_import_repo.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'ghostbrain.api.repo.import_atlassian'` (the `fake_atlassian` fixture imports it).

- [ ] **Step 4: Add the response/request models**

Create `ghostbrain/api/models/import_atlassian.py`:

```python
"""Schemas for the /v1/import route family."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ImportSpace(BaseModel):
    site: str
    siteSlug: str
    key: str
    name: str
    context: str


class ImportPage(BaseModel):
    site: str
    id: str
    title: str
    parentId: str | None = None
    hasChildren: bool
    updatedAt: str | None = None
    version: int | None = None
    space: str | None = None


class ConfluencePagesResponse(BaseModel):
    items: list[ImportPage]
    # Confluence v1 paging is start/limit; the cursor is the stringified
    # next start offset. None when the last page was not full.
    nextCursor: str | None = None


class ImportJiraIssue(BaseModel):
    site: str
    key: str
    summary: str
    status: str | None = None
    project: str | None = None
    updatedAt: str | None = None


class ImportItemRequest(BaseModel):
    kind: Literal["confluence_page", "jira_issue"]
    site: str
    id: str | None = None
    key: str | None = None

    @model_validator(mode="after")
    def _check_identifier(self) -> "ImportItemRequest":
        if self.kind == "confluence_page" and not self.id:
            raise ValueError("confluence_page items require `id`")
        if self.kind == "jira_issue" and not self.key:
            raise ValueError("jira_issue items require `key`")
        return self


class ImportRequest(BaseModel):
    # Spec: max 50 items per request; pydantic turns violations into 422.
    items: list[ImportItemRequest] = Field(..., min_length=1, max_length=50)


class ImportItemResult(BaseModel):
    kind: str
    id: str | None = None
    key: str | None = None
    ok: bool
    path: str | None = None
    context: str | None = None
    updated: bool | None = None
    error: str | None = None


class ImportResponse(BaseModel):
    results: list[ImportItemResult]
```

- [ ] **Step 5: Implement the repo browse half**

Create `ghostbrain/api/repo/import_atlassian.py`:

```python
"""Browse + import Confluence pages and Jira issues on demand.

Wraps the existing AtlassianClient and the connectors' module-level
normalization functions (extracted in the Task-1 refactor) so imported notes
are identical to scheduled-sync notes. Browse functions are read-only;
``import_items`` (the write half) persists + routes inline via the worker
pipeline — see its docstring.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ghostbrain.connectors.atlassian._base import (
    AtlassianAuthError,
    AtlassianClient,
    auth_for_site,
    slug_for_host,
)
from ghostbrain.connectors.confluence import PAGE_EXPAND, normalize_page
from ghostbrain.connectors.jira import JQL_FIELDS, MY_ISSUES_JQL, normalize_issue
from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.api.repo.import_atlassian")

CONFLUENCE_NOT_CONFIGURED = "confluence connector not configured — run onboarding"
JIRA_NOT_CONFIGURED = "jira connector not configured — run onboarding"
# Browse lists only need the row fields, not full descriptions.
BROWSE_FIELDS = "summary,status,project,updated"
DEFAULT_LIMIT = 25


class ImportNotConfiguredError(RuntimeError):
    """The relevant connector has no sites/spaces in routing.yaml, or its
    auth env vars are missing. Routes translate this to HTTP 409."""


# ──────────────────────────────────────────────────────────────────────────
# Config + auth
# ──────────────────────────────────────────────────────────────────────────

def _load_routing() -> dict:
    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


def _confluence_config(routing: dict) -> tuple[list[str], dict[str, str]]:
    cfg = routing.get("confluence") or {}
    # Confluence shares Atlassian sites with Jira when not configured
    # explicitly — same fallback as the scheduled runner's _build().
    sites = list(cfg.get("sites") or (routing.get("jira") or {}).get("sites") or [])
    spaces = dict(cfg.get("spaces") or {})
    if not sites or not spaces:
        raise ImportNotConfiguredError(CONFLUENCE_NOT_CONFIGURED)
    return sites, spaces


def _jira_sites(routing: dict) -> list[str]:
    sites = list((routing.get("jira") or {}).get("sites") or {})
    if not sites:
        raise ImportNotConfiguredError(JIRA_NOT_CONFIGURED)
    return sites


def _client(host: str, *, not_configured: str) -> AtlassianClient:
    try:
        email, token = auth_for_site(host)
    except AtlassianAuthError as e:
        # Missing env auth is a configuration problem (409), never a 500.
        log.info("atlassian auth missing for %s: %s", host, e)
        raise ImportNotConfiguredError(not_configured) from e
    return AtlassianClient(host, email, token)


# ──────────────────────────────────────────────────────────────────────────
# Browse (read-only)
# ──────────────────────────────────────────────────────────────────────────

def list_spaces() -> list[dict]:
    """Monitored spaces from routing.yaml, with best-effort display names."""
    routing = _load_routing()
    sites, spaces = _confluence_config(routing)
    out: list[dict] = []
    for host in sites:
        client = _client(host, not_configured=CONFLUENCE_NOT_CONFIGURED)
        names = _space_names(client, list(spaces.keys()))
        slug = slug_for_host(host)
        for key, context in spaces.items():
            out.append({
                "site": host,
                "siteSlug": slug,
                "key": key,
                "name": names.get(key, key),
                "context": context,
            })
    return out


def _space_names(client: AtlassianClient, keys: list[str]) -> dict[str, str]:
    """Best-effort key→display-name lookup; callers fall back to the key."""
    try:
        data = client.get(
            "/wiki/rest/api/space",
            params={"spaceKey": keys, "limit": max(len(keys), 1)},
        )
    except Exception as e:  # noqa: BLE001 — names are cosmetic
        log.warning("confluence space-name lookup failed: %s", e)
        return {}
    return {
        s["key"]: (s.get("name") or s["key"])
        for s in (data.get("results") or [])
        if isinstance(s, dict) and s.get("key")
    }


def list_confluence_pages(
    site: str,
    space: str,
    parent: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> dict:
    """Top-level pages of a monitored space, or children of ``parent``."""
    routing = _load_routing()
    sites, spaces = _confluence_config(routing)
    if site not in sites:
        raise ValueError(f"unknown confluence site: {site}")
    if space not in spaces:
        raise ValueError(f"space not monitored: {space}")
    start = int(cursor) if cursor and cursor.isdigit() else 0
    client = _client(site, not_configured=CONFLUENCE_NOT_CONFIGURED)
    params: dict = {
        "expand": "version,children.page",
        "limit": limit,
        "start": start,
    }
    if parent:
        data = client.get(f"/wiki/rest/api/content/{parent}/child/page", params=params)
    else:
        data = client.get(
            f"/wiki/rest/api/space/{space}/content/page",
            params={**params, "depth": "root"},
        )
    results = data.get("results") or []
    items = [
        _page_row(raw, site=site, space=space, parent_id=parent)
        for raw in results
    ]
    next_cursor = str(start + limit) if len(results) >= limit else None
    return {"items": items, "nextCursor": next_cursor}


def search_confluence(q: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """CQL ``title ~ q`` across the monitored spaces of every site."""
    routing = _load_routing()
    sites, spaces = _confluence_config(routing)
    quoted = q.replace('"', '\\"')
    space_clause = " OR ".join(f'space = "{k}"' for k in spaces)
    cql = f'type = page AND ({space_clause}) AND title ~ "{quoted}"'
    out: list[dict] = []
    for host in sites:
        client = _client(host, not_configured=CONFLUENCE_NOT_CONFIGURED)
        data = client.get(
            "/wiki/rest/api/content/search",
            params={"cql": cql, "expand": "version,space,children.page",
                    "limit": limit},
        )
        for raw in data.get("results") or []:
            out.append(_page_row(raw, site=host, space=None, parent_id=None))
    return out[:limit]


def _page_row(
    raw: dict, *, site: str, space: str | None, parent_id: str | None
) -> dict:
    version = raw.get("version") or {}
    children = (raw.get("children") or {}).get("page") or {}
    return {
        "site": site,
        "id": str(raw.get("id") or ""),
        "title": raw.get("title") or "",
        "parentId": parent_id,
        "hasChildren": int(children.get("size") or 0) > 0,
        "updatedAt": version.get("when"),
        "version": version.get("number"),
        "space": space or ((raw.get("space") or {}).get("key") or None),
    }


def list_jira_issues(q: str | None = None, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """No ``q``: the connector's my-issues JQL, newest first. With ``q``:
    ``text ~ q`` within the configured sites."""
    routing = _load_routing()
    sites = _jira_sites(routing)
    if q and q.strip():
        quoted = q.strip().replace('"', '\\"')
        jql = f'text ~ "{quoted}" ORDER BY updated DESC'
    else:
        jql = f"{MY_ISSUES_JQL} ORDER BY updated DESC"
    out: list[dict] = []
    for host in sites:
        client = _client(host, not_configured=JIRA_NOT_CONFIGURED)
        params = {"jql": jql, "fields": BROWSE_FIELDS, "maxResults": limit}
        try:
            data = client.get("/rest/api/3/search/jql", params=params)
        except Exception as e:  # noqa: BLE001 — same fallback as the connector
            log.info("falling back to legacy /search for %s: %s", host, e)
            data = client.get("/rest/api/3/search", params=params)
        for raw in data.get("issues") or []:
            fields = raw.get("fields") or {}
            out.append({
                "site": host,
                "key": raw.get("key") or "",
                "summary": (fields.get("summary") or "").strip(),
                "status": (fields.get("status") or {}).get("name"),
                "project": (fields.get("project") or {}).get("key"),
                "updatedAt": fields.get("updated"),
            })
    out.sort(key=lambda r: r["updatedAt"] or "", reverse=True)
    return out[:limit]
```

- [ ] **Step 6: Run test to verify it passes**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_import_repo.py -v
```
Expected: PASS — 11 tests green.

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/ -q
```
Expected: **68 passed** (57 baseline + 11 new).

- [ ] **Step 7: Commit**

```bash
git add ghostbrain/api/models/import_atlassian.py \
        ghostbrain/api/repo/import_atlassian.py \
        ghostbrain/api/tests/conftest.py \
        ghostbrain/api/tests/test_import_repo.py
git commit -m "feat(api): import repo browse — spaces/pages/search/issues + 409 detection"
```

---

## Task 3: Import repo — `import_items` (fetch → convert → persist → route inline → audit)

**Files:**
- Modify: `ghostbrain/api/repo/import_atlassian.py` (append the write half)
- Test: `ghostbrain/api/tests/test_import_items.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ghostbrain/api/tests/test_import_items.py`:

```python
"""import_items(): fetch + convert + persist (connector-identical) + inline
routing + audit + per-item error isolation. AtlassianClient is faked via the
conftest `fake_atlassian` registry; routing is path-based so no LLM runs."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from ghostbrain.api.tests.conftest import write_import_routing, write_live_config

PAGE_RAW = {
    "id": "1234567",
    "title": "ASCP architecture overview",
    "space": {"key": "DIG"},
    "version": {
        "number": 5,
        "when": "2026-05-07T09:30:00.000Z",
        "by": {"accountId": "u1", "displayName": "Jannik"},
    },
    "body": {
        "storage": {
            "value": "<p>This is the <strong>ASCP</strong> overview.</p>",
        },
    },
    "_links": {
        "base": "https://sft.atlassian.net/wiki",
        "webui": "/spaces/DIG/pages/1234567/Overview",
    },
}

ISSUE_RAW = {
    "key": "DIGISURE-1234",
    "id": "10001",
    "fields": {
        "summary": "Add cashback to quote domain",
        "status": {"name": "In Progress",
                   "statusCategory": {"key": "indeterminate"}},
        "priority": {"name": "Medium"},
        "issuetype": {"name": "Story"},
        "assignee": {"accountId": "abc", "displayName": "Jannik"},
        "reporter": {"accountId": "def", "displayName": "Reporter"},
        "labels": ["capstone"],
        "project": {"key": "DIGISURE"},
        "created": "2026-05-01T08:00:00.000+0000",
        "updated": "2026-05-07T10:00:00.000+0000",
        "description": {
            "type": "doc",
            "content": [{
                "type": "paragraph",
                "content": [{"type": "text", "text": "Add a cashback field..."}],
            }],
        },
    },
}

PAGE_ITEM = {"kind": "confluence_page", "site": "sft.atlassian.net", "id": "1234567"}
ISSUE_ITEM = {"kind": "jira_issue", "site": "sft.atlassian.net", "key": "DIGISURE-1234"}


@pytest.fixture
def configured_vault(tmp_vault: Path) -> Path:
    write_import_routing(tmp_vault)
    write_live_config(tmp_vault)
    return tmp_vault


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.find("\n---", 4)
    return yaml.safe_load(text[4:end])


def _audit_lines(vault: Path) -> list[dict]:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    f = vault / "90-meta" / "audit" / f"{day}.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]


def test_import_confluence_page_writes_routed_note_and_audit(
    configured_vault: Path, fake_atlassian
):
    from ghostbrain.api.repo.import_atlassian import import_items

    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = PAGE_RAW
    results = import_items([PAGE_ITEM])

    assert len(results) == 1
    r = results[0]
    assert r["kind"] == "confluence_page"
    assert r["id"] == "1234567"
    assert r["ok"] is True
    assert r["context"] == "sanlam"
    assert r["updated"] is False
    assert r["path"].startswith("20-contexts/sanlam/confluence/")

    # fetched with the connector's exact expand set
    host, path, params = fake_atlassian.calls[-1]
    assert params == {"expand": "body.storage,version,space,history"}

    note = configured_vault / r["path"]
    fm = _frontmatter(note)
    assert fm["id"] == "confluence:sft:1234567"
    assert fm["source"] == "confluence"
    assert fm["space"] == "DIG"
    assert fm["context"] == "sanlam"
    assert fm["routingMethod"] == "path"
    assert fm["sourceUrl"].endswith("/spaces/DIG/pages/1234567/Overview")
    assert "**ASCP**" in note.read_text()

    # inbox copy exists too (write_note always writes it)
    inbox = configured_vault / "00-inbox" / "raw" / "confluence"
    assert len(list(inbox.glob("*.md"))) == 1

    audits = [a for a in _audit_lines(configured_vault)
              if a["event_type"] == "import_completed"]
    assert len(audits) == 1
    assert audits[0]["event_id"] == "confluence:sft:1234567"
    assert audits[0]["source"] == "confluence"
    assert audits[0]["ok"] is True
    assert audits[0]["context"] == "sanlam"


def test_import_jira_issue_writes_routed_note(configured_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import import_items

    fake_atlassian.routes["/rest/api/3/issue/DIGISURE-1234"] = ISSUE_RAW
    results = import_items([ISSUE_ITEM])

    r = results[0]
    assert r["ok"] is True
    assert r["key"] == "DIGISURE-1234"
    assert r["path"].startswith("20-contexts/sanlam/jira/tickets/")
    fm = _frontmatter(configured_vault / r["path"])
    assert fm["id"] == "jira:sft:DIGISURE-1234"
    assert fm["key"] == "DIGISURE-1234"
    assert fm["status"] == "In Progress"
    # fetched with the connector's full field list (body fidelity)
    host, path, params = fake_atlassian.calls[-1]
    from ghostbrain.connectors.jira import JQL_FIELDS
    assert params == {"fields": JQL_FIELDS}


def test_reimport_unchanged_page_overwrites_same_path_updated_true(
    configured_vault: Path, fake_atlassian
):
    from ghostbrain.api.repo.import_atlassian import import_items

    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = PAGE_RAW
    first = import_items([PAGE_ITEM])[0]
    second = import_items([PAGE_ITEM])[0]

    assert first["updated"] is False
    assert second["updated"] is True
    assert second["path"] == first["path"]
    ctx_dir = configured_vault / "20-contexts" / "sanlam" / "confluence"
    assert len(list(ctx_dir.glob("*.md"))) == 1
    inbox = configured_vault / "00-inbox" / "raw" / "confluence"
    assert len(list(inbox.glob("*.md"))) == 1


def test_reimport_changed_page_removes_stale_note(
    configured_vault: Path, fake_atlassian
):
    from ghostbrain.api.repo.import_atlassian import import_items

    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = PAGE_RAW
    first = import_items([PAGE_ITEM])[0]

    # The page gets edited: new version timestamp + new title → the
    # connector filename changes, so the old note would be a stale duplicate.
    changed = {
        **PAGE_RAW,
        "title": "ASCP architecture overview v2",
        "version": {**PAGE_RAW["version"],
                    "number": 6, "when": "2026-06-09T12:00:00.000Z"},
    }
    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = changed
    second = import_items([PAGE_ITEM])[0]

    assert second["updated"] is True
    assert second["path"] != first["path"]
    ctx_dir = configured_vault / "20-contexts" / "sanlam" / "confluence"
    assert len(list(ctx_dir.glob("*.md"))) == 1  # stale copy removed
    assert not (configured_vault / first["path"]).exists()
    inbox = configured_vault / "00-inbox" / "raw" / "confluence"
    assert len(list(inbox.glob("*.md"))) == 1


def test_failed_item_is_isolated_and_audited(configured_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import import_items

    def not_found(path, params):
        raise RuntimeError("atlassian GET failed (last status=404)")

    fake_atlassian.routes["/wiki/rest/api/content/999"] = not_found
    fake_atlassian.routes["/rest/api/3/issue/DIGISURE-1234"] = ISSUE_RAW

    results = import_items([
        {"kind": "confluence_page", "site": "sft.atlassian.net", "id": "999"},
        ISSUE_ITEM,
    ])
    assert results[0]["ok"] is False
    assert "404" in results[0]["error"]
    assert results[1]["ok"] is True  # the failure never aborts the batch

    audits = [a for a in _audit_lines(configured_vault)
              if a["event_type"] == "import_completed"]
    assert [a["ok"] for a in audits] == [False, True]


def test_import_items_validates_config_upfront(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import (
        ImportNotConfiguredError,
        import_items,
    )

    # no routing.yaml → 409-shaped error BEFORE any item is attempted
    with pytest.raises(ImportNotConfiguredError):
        import_items([PAGE_ITEM])
    assert fake_atlassian.calls == []


def test_import_output_identical_to_scheduled_sync(
    configured_vault: Path, fake_atlassian, monkeypatch: pytest.MonkeyPatch
):
    """The byte-compat guarantee: an imported note equals the note the worker
    writes for the same connector event, modulo the ingestedAt timestamp."""
    from datetime import datetime as dt, timezone as tz
    from ghostbrain.api.repo.import_atlassian import import_items
    from ghostbrain.connectors.confluence import ConfluenceConnector
    from ghostbrain.worker.pipeline import process_event

    # 1) Scheduled-sync path: connector fetch (mocked HTTP) → worker pipeline.
    monkeypatch.setattr(
        "ghostbrain.connectors.confluence.AtlassianClient.get",
        lambda self, path, params=None, **kw: {"results": [PAGE_RAW]},
    )
    connector = ConfluenceConnector(
        config={"sites": ["sft.atlassian.net"], "spaces": {"DIG": "sanlam"}},
        queue_dir=configured_vault / "q",
        state_dir=configured_vault / "s",
    )
    events = connector.fetch(dt(2026, 5, 6, tzinfo=tz.utc))
    assert len(events) == 1
    summary = process_event(events[0])
    sync_path = Path(summary["context_path"])
    sync_text = sync_path.read_text(encoding="utf-8")

    # wipe the synced files so the import starts from a clean vault
    Path(summary["inbox_path"]).unlink()
    sync_path.unlink()

    # 2) Import path.
    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = PAGE_RAW
    result = import_items([PAGE_ITEM])[0]
    import_path = configured_vault / result["path"]

    assert import_path.name == sync_path.name  # same deterministic filename

    def normalize(text: str) -> str:
        return re.sub(r"^ingestedAt: .*$", "ingestedAt: X", text, flags=re.M)

    assert normalize(import_path.read_text(encoding="utf-8")) == normalize(sync_text)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_import_items.py -v
```
Expected: FAIL — `ImportError: cannot import name 'import_items'`.

- [ ] **Step 3: Implement — append the write half to `ghostbrain/api/repo/import_atlassian.py`**

Append at the end of the file:

```python
# ──────────────────────────────────────────────────────────────────────────
# Import (write)
# ──────────────────────────────────────────────────────────────────────────

def import_items(items: list[dict]) -> list[dict]:
    """Import each item sequentially; a failed item never aborts the batch.

    Mechanism (mirrors the scheduled pipeline exactly): the scheduled sync
    enqueues normalized events into 90-meta/queue/pending and the worker's
    run_loop feeds each one to ghostbrain.worker.pipeline.process_event,
    which routes (path-first, LLM fallback) and persists via write_note.
    Import skips the queue hop and calls process_event inline on the same
    normalized event — identical frontmatter, body, filename, and routing
    fallback (low confidence → inbox manual_review), one call per item.

    Raises ImportNotConfiguredError (→ 409) up front when the connector for
    any requested kind has no routing config or no auth env vars. Everything
    after that is per-item: failures become {"ok": False, "error": ...}.
    """
    routing = _load_routing()
    kinds = {i.get("kind") for i in items}
    # Validate config + auth BEFORE touching any item (spec: 409, not a
    # batch of per-item failures). auth_for_site only reads env vars.
    if "confluence_page" in kinds:
        sites, _spaces = _confluence_config(routing)
        _client(sites[0], not_configured=CONFLUENCE_NOT_CONFIGURED)
    if "jira_issue" in kinds:
        jira_sites = _jira_sites(routing)
        _client(jira_sites[0], not_configured=JIRA_NOT_CONFIGURED)
    return [_import_one(item, routing) for item in items]


def _import_one(item: dict, routing: dict) -> dict:
    from ghostbrain.worker.audit import audit_log

    kind = item.get("kind")
    ident: dict = {"kind": kind}
    if kind == "confluence_page":
        ident["id"] = item.get("id")
    else:
        ident["key"] = item.get("key")
    try:
        event = _fetch_event(item, routing)
        existing = _existing_note_paths(event["id"], source=event["source"])
        summary = _process(event)
        written = {
            str(Path(p).resolve())
            for p in (summary.get("inbox_path"), summary.get("context_path"))
            if p
        }
        for old in existing:
            if str(old.resolve()) not in written:
                # The connector filename embeds timestamp+title; an item that
                # changed since its last sync/import lands at a NEW filename.
                # Remove the stale copy so re-import updates, not duplicates.
                old.unlink(missing_ok=True)
        path = summary.get("context_path") or summary.get("inbox_path")
        rel = _vault_relative(path)
        audit_log(
            "import_completed",
            event["id"],
            source=event["source"],
            ok=True,
            context=summary.get("context"),
            path=rel,
        )
        return {
            **ident,
            "ok": True,
            "path": rel,
            "context": summary.get("context"),
            "updated": bool(existing),
        }
    except Exception as e:  # noqa: BLE001 — per-item isolation is the contract
        log.warning("import failed for %s: %s", ident, e)
        audit_log(
            "import_completed",
            ident.get("id") or ident.get("key") or "?",
            source="confluence" if kind == "confluence_page" else "jira",
            ok=False,
            error=str(e),
        )
        return {**ident, "ok": False, "error": str(e)}


def _fetch_event(item: dict, routing: dict) -> dict:
    """Fetch full content for one item and run the connector's conversion."""
    kind = item.get("kind")
    host = item.get("site") or ""
    if kind == "confluence_page":
        _sites, spaces = _confluence_config(routing)
        client = _client(host, not_configured=CONFLUENCE_NOT_CONFIGURED)
        raw = client.get(
            f"/wiki/rest/api/content/{item['id']}",
            params={"expand": PAGE_EXPAND},
        )
        event = normalize_page(raw, host=host, space_map=spaces)
        if event is None:
            raise ValueError(
                "page is not importable (missing id or unmonitored space)"
            )
        return event
    if kind == "jira_issue":
        _jira_sites(routing)
        client = _client(host, not_configured=JIRA_NOT_CONFIGURED)
        raw = client.get(
            f"/rest/api/3/issue/{item['key']}",
            params={"fields": JQL_FIELDS},
        )
        return normalize_issue(raw, host=host)
    raise ValueError(f"unknown import kind: {kind}")


def _process(event: dict) -> dict:
    # Imported lazily: the pipeline pulls in the claude-code parser, the LLM
    # client, and the extractor — none of which the browse endpoints need.
    from ghostbrain.worker.pipeline import process_event

    return process_event(event)


def _existing_note_paths(note_id: str, *, source: str) -> list[Path]:
    """All vault notes whose frontmatter id matches this event id.

    Searched in the same places write_note writes: the durable inbox and the
    per-context source dirs (jira notes live under jira/tickets/)."""
    vault = vault_path()
    sub = "jira/tickets" if source == "jira" else source
    dirs = [vault / "00-inbox" / "raw" / source]
    dirs.extend(sorted((vault / "20-contexts").glob(f"*/{sub}")))
    found: list[Path] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            if _frontmatter_id(p) == note_id:
                found.append(p)
    return found


def _frontmatter_id(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return fm.get("id") if isinstance(fm, dict) else None


def _vault_relative(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return str(Path(path).resolve().relative_to(vault_path().resolve()))
    except ValueError:
        return str(path)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_import_items.py -v
```
Expected: PASS — 7 tests green. (If `test_import_output_identical_to_scheduled_sync` fails, the import path has drifted from the worker path — fix the repo, never the normalizer.)

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/ -q
```
Expected: **75 passed** (68 + 7).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/import_atlassian.py \
        ghostbrain/api/tests/test_import_items.py
git commit -m "feat(api): import_items — inline pipeline routing, dedup by note id, per-item audit"
```

---

## Task 4: Routes — GET browse endpoints + POST /v1/import

**Files:**
- Create: `ghostbrain/api/routes/import_atlassian.py`
- Modify: `ghostbrain/api/main.py`
- Test: `ghostbrain/api/tests/test_import_routes.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ghostbrain/api/tests/test_import_routes.py`:

```python
"""/v1/import route family: browse endpoints, bulk POST, 409/422 mapping."""
from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.api.tests.conftest import write_import_routing, write_live_config
from ghostbrain.api.tests.test_import_items import ISSUE_RAW, PAGE_RAW
from ghostbrain.api.tests.test_import_repo import ISSUE_LIST_ITEM, PAGE_LIST_ITEM

CONFLUENCE_409 = "confluence connector not configured — run onboarding"
JIRA_409 = "jira connector not configured — run onboarding"


def test_spaces_ok(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/space"] = {
        "results": [{"key": "DIG", "name": "Digisure"}]
    }
    res = client.get("/v1/import/confluence/spaces", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert {s["key"] for s in data} == {"DIG", "SPE"}
    by_key = {s["key"]: s for s in data}
    assert by_key["DIG"]["name"] == "Digisure"
    assert by_key["SPE"]["name"] == "SPE"  # lookup miss → key fallback
    assert by_key["DIG"]["siteSlug"] == "sft"
    assert by_key["DIG"]["context"] == "sanlam"


def test_spaces_409_when_unconfigured(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    res = client.get("/v1/import/confluence/spaces", headers=auth_headers)
    assert res.status_code == 409
    assert res.json() == {"detail": CONFLUENCE_409}


def test_pages_ok_passes_params(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/content/100/child/page"] = {
        "results": [PAGE_LIST_ITEM]
    }
    res = client.get(
        "/v1/import/confluence/pages"
        "?site=sft.atlassian.net&space=DIG&parent=100&limit=1&cursor=3",
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["items"][0]["id"] == "100"
    assert data["items"][0]["parentId"] == "100"
    assert data["nextCursor"] == "4"  # full page (1 of limit 1) → start+limit
    host, path, params = fake_atlassian.calls[-1]
    assert params["start"] == 3
    assert params["limit"] == 1


def test_pages_requires_site_and_space(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    assert client.get(
        "/v1/import/confluence/pages?space=DIG", headers=auth_headers
    ).status_code == 422
    assert client.get(
        "/v1/import/confluence/pages?site=sft.atlassian.net", headers=auth_headers
    ).status_code == 422
    # unmonitored space → 422 (repo ValueError), not 500
    assert client.get(
        "/v1/import/confluence/pages?site=sft.atlassian.net&space=NOPE",
        headers=auth_headers,
    ).status_code == 422


def test_search_ok(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/content/search"] = {
        "results": [PAGE_LIST_ITEM]
    }
    res = client.get("/v1/import/confluence/search?q=arch", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()[0]["title"] == "ASCP architecture"
    host, path, params = fake_atlassian.calls[-1]
    assert 'title ~ "arch"' in params["cql"]


def test_jira_issues_ok(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    fake_atlassian.routes["/rest/api/3/search/jql"] = {"issues": [ISSUE_LIST_ITEM]}
    res = client.get("/v1/import/jira/issues", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()[0]["key"] == "DIGISURE-1"

    res = client.get("/v1/import/jira/issues?q=bff", headers=auth_headers)
    assert res.status_code == 200
    host, path, params = fake_atlassian.calls[-1]
    assert params["jql"].startswith('text ~ "bff"')


def test_jira_issues_409_when_only_confluence_configured(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault, jira=False)
    res = client.get("/v1/import/jira/issues", headers=auth_headers)
    assert res.status_code == 409
    assert res.json() == {"detail": JIRA_409}


def test_post_import_happy_path_writes_note(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    write_live_config(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = PAGE_RAW
    fake_atlassian.routes["/rest/api/3/issue/DIGISURE-1234"] = ISSUE_RAW
    res = client.post("/v1/import", headers=auth_headers, json={"items": [
        {"kind": "confluence_page", "site": "sft.atlassian.net", "id": "1234567"},
        {"kind": "jira_issue", "site": "sft.atlassian.net", "key": "DIGISURE-1234"},
    ]})
    assert res.status_code == 200
    results = res.json()["results"]
    assert [r["ok"] for r in results] == [True, True]
    assert results[0]["path"].startswith("20-contexts/sanlam/confluence/")
    assert results[0]["updated"] is False
    assert results[1]["path"].startswith("20-contexts/sanlam/jira/tickets/")
    assert (tmp_vault / results[0]["path"]).exists()
    assert (tmp_vault / results[1]["path"]).exists()


def test_post_import_max_50_items(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    item = {"kind": "jira_issue", "site": "sft.atlassian.net", "key": "X-1"}
    res = client.post("/v1/import", headers=auth_headers,
                      json={"items": [item] * 51})
    assert res.status_code == 422
    res = client.post("/v1/import", headers=auth_headers, json={"items": []})
    assert res.status_code == 422


def test_post_import_409_when_unconfigured(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    res = client.post("/v1/import", headers=auth_headers, json={"items": [
        {"kind": "confluence_page", "site": "sft.atlassian.net", "id": "1"},
    ]})
    assert res.status_code == 409
    assert res.json() == {"detail": CONFLUENCE_409}


def test_post_import_item_missing_identifier_422(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    res = client.post("/v1/import", headers=auth_headers, json={"items": [
        {"kind": "confluence_page", "site": "sft.atlassian.net"},  # no id
    ]})
    assert res.status_code == 422
    res = client.post("/v1/import", headers=auth_headers, json={"items": [
        {"kind": "jira_issue", "site": "sft.atlassian.net"},  # no key
    ]})
    assert res.status_code == 422


def test_post_import_per_item_failure_isolated(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    write_live_config(tmp_vault)

    def gone(path, params):
        raise RuntimeError("atlassian GET failed (last status=404)")

    fake_atlassian.routes["/wiki/rest/api/content/999"] = gone
    fake_atlassian.routes["/rest/api/3/issue/DIGISURE-1234"] = ISSUE_RAW
    res = client.post("/v1/import", headers=auth_headers, json={"items": [
        {"kind": "confluence_page", "site": "sft.atlassian.net", "id": "999"},
        {"kind": "jira_issue", "site": "sft.atlassian.net", "key": "DIGISURE-1234"},
    ]})
    assert res.status_code == 200
    results = res.json()["results"]
    assert results[0]["ok"] is False
    assert "404" in results[0]["error"]
    assert results[1]["ok"] is True
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_import_routes.py -v
```
Expected: FAIL — every request returns 404 (router not registered).

- [ ] **Step 3: Implement the routes**

Create `ghostbrain/api/routes/import_atlassian.py`:

```python
"""/v1/import — browse Confluence/Jira and bulk-import items into the vault."""
from fastapi import APIRouter, HTTPException, Query

from ghostbrain.api.models.import_atlassian import (
    ConfluencePagesResponse,
    ImportJiraIssue,
    ImportPage,
    ImportRequest,
    ImportResponse,
    ImportSpace,
)
from ghostbrain.api.repo import import_atlassian as repo
from ghostbrain.api.repo.import_atlassian import ImportNotConfiguredError

router = APIRouter(prefix="/v1/import", tags=["import"])


@router.get("/confluence/spaces", response_model=list[ImportSpace])
def confluence_spaces() -> list[dict]:
    try:
        return repo.list_spaces()
    except ImportNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/confluence/pages", response_model=ConfluencePagesResponse)
def confluence_pages(
    site: str = Query(...),
    space: str = Query(...),
    parent: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: str | None = Query(None),
) -> dict:
    try:
        return repo.list_confluence_pages(
            site=site, space=space, parent=parent, limit=limit, cursor=cursor
        )
    except ImportNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        # unknown site / unmonitored space — a client mistake, not a 500
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/confluence/search", response_model=list[ImportPage])
def confluence_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(25, ge=1, le=100),
) -> list[dict]:
    try:
        return repo.search_confluence(q=q, limit=limit)
    except ImportNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/jira/issues", response_model=list[ImportJiraIssue])
def jira_issues(
    q: str | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
) -> list[dict]:
    try:
        return repo.list_jira_issues(q=q, limit=limit)
    except ImportNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("", response_model=ImportResponse)
def bulk_import(payload: ImportRequest) -> dict:
    # >50 / empty / missing id|key → 422 from the pydantic model before we
    # ever get here. Unconfigured connector → 409 from the upfront check.
    try:
        results = repo.import_items([i.model_dump() for i in payload.items])
    except ImportNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"results": results}
```

- [ ] **Step 4: Register the router**

Edit `ghostbrain/api/main.py`:

1. In the import block, after `from ghostbrain.api.routes import daily as daily_routes`, add:
   ```python
   from ghostbrain.api.routes import import_atlassian as import_routes
   ```
2. In `create_app`, after `app.include_router(daily_routes.router)`, add:
   ```python
   app.include_router(import_routes.router)
   ```

- [ ] **Step 5: Run test to verify it passes**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_import_routes.py -v
```
Expected: PASS — 12 tests green.

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/ -q
```
Expected: **87 passed** (75 + 12).

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/routes/import_atlassian.py ghostbrain/api/main.py \
        ghostbrain/api/tests/test_import_routes.py
git commit -m "feat(api): /v1/import route family — browse + bulk import with 409/422 mapping"
```

---

## Task 5: Desktop — shared API types, `ApiError` with status, React Query hooks

**Files:**
- Modify: `desktop/src/shared/api-types.ts`
- Modify: `desktop/src/renderer/lib/api/client.ts`
- Modify: `desktop/src/renderer/lib/api/hooks.ts`
- Test: `desktop/src/renderer/__tests__/import-hooks.test.tsx` (create)

- [ ] **Step 1: Write the failing test**

Create `desktop/src/renderer/__tests__/import-hooks.test.tsx`:

```tsx
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ApiError } from '../lib/api/client';
import {
  useConfluencePages,
  useConfluenceSearch,
  useImportItems,
  useImportSpaces,
  useJiraIssues,
} from '../lib/api/hooks';
import type { ImportItem, ImportResponse } from '../../shared/api-types';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  window.gb.api.request = apiRequest as typeof window.gb.api.request;
});

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useImportSpaces', () => {
  it('fetches /v1/import/confluence/spaces', async () => {
    apiRequest.mockResolvedValueOnce({ ok: true, data: [] });
    const { result } = renderHook(() => useImportSpaces(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/import/confluence/spaces');
  });

  it('surfaces a 409 as ApiError with status', async () => {
    apiRequest.mockResolvedValue({
      ok: false,
      error: 'confluence connector not configured — run onboarding',
      status: 409,
    });
    const { result } = renderHook(() => useImportSpaces(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    const err = result.current.error;
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    // retry: false → exactly one request, the CTA renders immediately
    expect(apiRequest).toHaveBeenCalledTimes(1);
  });
});

describe('useConfluencePages', () => {
  it('fetches pages with site/space/parent params', async () => {
    apiRequest.mockResolvedValueOnce({
      ok: true,
      data: { items: [], nextCursor: null },
    });
    const { result } = renderHook(
      () => useConfluencePages('sft.atlassian.net', 'DIG', '100'),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith(
      'GET',
      '/v1/import/confluence/pages?site=sft.atlassian.net&space=DIG&parent=100',
    );
  });

  it('does not fetch when site or space is null', () => {
    renderHook(() => useConfluencePages(null, null), { wrapper: makeWrapper() });
    expect(apiRequest).not.toHaveBeenCalled();
  });
});

describe('useConfluenceSearch', () => {
  it('does not fetch under 2 characters', () => {
    renderHook(() => useConfluenceSearch('a'), { wrapper: makeWrapper() });
    expect(apiRequest).not.toHaveBeenCalled();
  });

  it('fetches with an encoded query', async () => {
    apiRequest.mockResolvedValueOnce({ ok: true, data: [] });
    const { result } = renderHook(() => useConfluenceSearch('quote domain'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith(
      'GET',
      '/v1/import/confluence/search?q=quote%20domain',
    );
  });
});

describe('useJiraIssues', () => {
  it('fetches my issues when no query', async () => {
    apiRequest.mockResolvedValueOnce({ ok: true, data: [] });
    const { result } = renderHook(() => useJiraIssues(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/import/jira/issues');
  });

  it('fetches a text search when a query is set', async () => {
    apiRequest.mockResolvedValueOnce({ ok: true, data: [] });
    const { result } = renderHook(() => useJiraIssues('cashback'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith(
      'GET',
      '/v1/import/jira/issues?q=cashback',
    );
  });
});

describe('useImportItems', () => {
  const items: ImportItem[] = [
    { kind: 'confluence_page', site: 'sft.atlassian.net', id: '100' },
    { kind: 'jira_issue', site: 'sft.atlassian.net', key: 'DIGISURE-1' },
  ];

  it('POSTs one item at a time and reports progress', async () => {
    apiRequest.mockImplementation(async (_m: string, _p: string, body?: unknown) => {
      const item = (body as { items: ImportItem[] }).items[0]!;
      return {
        ok: true,
        data: {
          results: [{
            kind: item.kind,
            id: item.id ?? null,
            key: item.key ?? null,
            ok: true,
            path: 'x.md',
            context: 'sanlam',
            updated: false,
            error: null,
          }],
        },
      };
    });
    const onItem = vi.fn();
    const { result } = renderHook(() => useImportItems(), { wrapper: makeWrapper() });
    let res: ImportResponse | undefined;
    await act(async () => {
      res = await result.current.mutateAsync({ items, onItem });
    });
    expect(apiRequest).toHaveBeenCalledTimes(2);
    expect(apiRequest).toHaveBeenNthCalledWith(1, 'POST', '/v1/import', {
      items: [items[0]],
    });
    expect(apiRequest).toHaveBeenNthCalledWith(2, 'POST', '/v1/import', {
      items: [items[1]],
    });
    expect(onItem).toHaveBeenNthCalledWith(1, 0, 2, items[0]);
    expect(onItem).toHaveBeenNthCalledWith(2, 1, 2, items[1]);
    expect(res!.results).toHaveLength(2);
    expect(res!.results.map((r) => r.ok)).toEqual([true, true]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd desktop && npx vitest run src/renderer/__tests__/import-hooks.test.tsx
```
Expected: FAIL — `ApiError` is not exported from `../lib/api/client`, and the import hooks are not exported from `../lib/api/hooks`.

- [ ] **Step 3: Add the shared types**

Edit `desktop/src/shared/api-types.ts` — append at the end of the file (after the `Prep` interface):

```typescript
// ── Atlassian import (mirrors ghostbrain/api/models/import_atlassian.py) ──

export interface ImportSpace {
  site: string;
  siteSlug: string;
  key: string;
  name: string;
  context: string;
}

export interface ImportPage {
  site: string;
  id: string;
  title: string;
  parentId: string | null;
  hasChildren: boolean;
  updatedAt: string | null;
  version: number | null;
  space: string | null;
}

export interface ConfluencePagesResponse {
  items: ImportPage[];
  nextCursor: string | null;
}

export interface ImportJiraIssue {
  site: string;
  key: string;
  summary: string;
  status: string | null;
  project: string | null;
  updatedAt: string | null;
}

export type ImportItemKind = 'confluence_page' | 'jira_issue';

export interface ImportItem {
  kind: ImportItemKind;
  site: string;
  id?: string;
  key?: string;
}

export interface ImportItemResult {
  kind: ImportItemKind;
  id?: string | null;
  key?: string | null;
  ok: boolean;
  path?: string | null;
  context?: string | null;
  updated?: boolean | null;
  error?: string | null;
}

export interface ImportResponse {
  results: ImportItemResult[];
}
```

- [ ] **Step 4: Add `ApiError` to the client**

Replace `desktop/src/renderer/lib/api/client.ts` with:

```typescript
/** Error from the sidecar API, carrying the HTTP status when one exists.
 * The main-process forwarder already extracts FastAPI's `detail` string and
 * the status code; previously the renderer threw a plain Error and dropped
 * the status — the import screen needs it to tell "409 connector not
 * configured" (call-to-action) apart from real failures (error panel). */
export class ApiError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export async function get<T>(
  path: string,
  opts?: { signal?: AbortSignal },
): Promise<T> {
  // Honor signal at the renderer boundary — by the time we hit the IPC
  // bridge the request is already in flight in the main process. A
  // cancelled signal here at least prevents us from awaiting a result
  // whose query key has changed underneath us (React Query's main use
  // case: user clicked a different filter mid-fetch).
  if (opts?.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const result = await window.gb.api.request<T>('GET', path);
  if (opts?.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  if (!result.ok) throw new ApiError(result.error, result.status);
  return result.data;
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const result = await window.gb.api.request<T>('POST', path, body);
  if (!result.ok) throw new ApiError(result.error, result.status);
  return result.data;
}
```

(`ApiError extends Error`, so every existing `error instanceof Error` check and `error.message` render keeps working unchanged.)

- [ ] **Step 5: Add the hooks**

Edit `desktop/src/renderer/lib/api/hooks.ts`:

1. In the `import type { ... } from '../../../shared/api-types';` block, add (alphabetically):
   ```typescript
   ConfluencePagesResponse,
   ImportItem,
   ImportItemResult,
   ImportJiraIssue,
   ImportPage,
   ImportResponse,
   ImportSpace,
   ```
2. Append at the end of the file:

```typescript
// ── Atlassian import ──────────────────────────────────────────────────────

export function useImportSpaces() {
  return useQuery({
    queryKey: ['import', 'spaces'],
    queryFn: () => get<ImportSpace[]>('/v1/import/confluence/spaces'),
    staleTime: 5 * 60_000,
    // A 409 (connector not configured) must render the call-to-action
    // immediately — never spin through React Query's default 3 retries.
    retry: false,
  });
}

export function useConfluencePages(
  site: string | null,
  space: string | null,
  parent?: string,
) {
  const params = new URLSearchParams();
  if (site) params.set('site', site);
  if (space) params.set('space', space);
  if (parent) params.set('parent', parent);
  return useQuery({
    queryKey: ['import', 'pages', site, space, parent ?? null],
    queryFn: () =>
      get<ConfluencePagesResponse>(`/v1/import/confluence/pages?${params.toString()}`),
    enabled: site !== null && space !== null,
    staleTime: 60_000,
    retry: false,
  });
}

export function useConfluenceSearch(q: string) {
  return useQuery({
    queryKey: ['import', 'confluence-search', q],
    queryFn: () =>
      get<ImportPage[]>(`/v1/import/confluence/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length >= 2,
    staleTime: 30_000,
    retry: false,
  });
}

export function useJiraIssues(q?: string) {
  const trimmed = (q ?? '').trim();
  return useQuery({
    queryKey: ['import', 'jira-issues', trimmed],
    queryFn: () =>
      get<ImportJiraIssue[]>(
        `/v1/import/jira/issues${trimmed ? `?q=${encodeURIComponent(trimmed)}` : ''}`,
      ),
    staleTime: 30_000,
    retry: false,
  });
}

export interface ImportRunVars {
  items: ImportItem[];
  /** Called before each item is sent — drives the "3/7 — importing …" UI. */
  onItem?: (done: number, total: number, current: ImportItem) => void;
}

export function useImportItems() {
  const qc = useQueryClient();
  return useMutation({
    // One POST per item (each a valid 1-item batch for /v1/import): the
    // sidecar processes synchronously, so this is what gives the UI real
    // per-item progress. The endpoint itself accepts up to 50 items per
    // request for non-interactive callers.
    mutationFn: async ({ items, onItem }: ImportRunVars): Promise<ImportResponse> => {
      const results: ImportItemResult[] = [];
      for (let i = 0; i < items.length; i += 1) {
        const item = items[i]!;
        onItem?.(i, items.length, item);
        const res = await post<ImportResponse>('/v1/import', { items: [item] });
        results.push(...res.results);
      }
      return { results };
    },
    onSettled: () => {
      // Imported notes surface as captures, audit/import_completed events
      // (activity feed + heatmap), and vault stats.
      qc.invalidateQueries({ queryKey: ['captures'] });
      qc.invalidateQueries({ queryKey: ['activity'] });
      qc.invalidateQueries({ queryKey: ['vault'] });
    },
  });
}
```

- [ ] **Step 6: Run test + typecheck to verify it passes**

```bash
cd desktop && npx vitest run src/renderer/__tests__/import-hooks.test.tsx
```
Expected: PASS — 8 tests green.

```bash
cd desktop && npx vitest run && npm run typecheck
```
Expected: **45 passed** (37 baseline + 8 new), typecheck clean (the `ApiError` change is source-compatible with every existing call site).

- [ ] **Step 7: Commit**

```bash
git add desktop/src/shared/api-types.ts \
        desktop/src/renderer/lib/api/client.ts \
        desktop/src/renderer/lib/api/hooks.ts \
        desktop/src/renderer/__tests__/import-hooks.test.tsx
git commit -m "feat(desktop): import api types, ApiError with status, import hooks"
```

---

## Task 6: Import screen — tabs, checkbox lists, search, selection bar, progress + nav wiring

**Files:**
- Create: `desktop/src/renderer/screens/import.tsx`
- Modify: `desktop/src/renderer/stores/navigation.ts`
- Modify: `desktop/src/renderer/components/Sidebar.tsx`
- Modify: `desktop/src/renderer/App.tsx`
- Test: `desktop/src/renderer/__tests__/ImportScreen.test.tsx` (create)
- Test: `desktop/src/renderer/__tests__/App.test.tsx` (extend)

- [ ] **Step 1: Write the failing screen test**

Create `desktop/src/renderer/__tests__/ImportScreen.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ImportScreen } from '../screens/import';
import { useNavigation } from '../stores/navigation';
import type {
  ConfluencePagesResponse,
  ImportJiraIssue,
  ImportPage,
  ImportSpace,
} from '../../shared/api-types';

const spaces: ImportSpace[] = [
  { site: 'sft.atlassian.net', siteSlug: 'sft', key: 'DIG', name: 'Digisure', context: 'sanlam' },
  { site: 'sft.atlassian.net', siteSlug: 'sft', key: 'SPE', name: 'Short-term', context: 'sanlam' },
];

const digPages: ConfluencePagesResponse = {
  items: [
    { site: 'sft.atlassian.net', id: '100', title: 'ASCP architecture', parentId: null,
      hasChildren: true, updatedAt: '2026-06-01T10:00:00.000Z', version: 4, space: 'DIG' },
    { site: 'sft.atlassian.net', id: '200', title: 'Runbooks', parentId: null,
      hasChildren: false, updatedAt: null, version: 1, space: 'DIG' },
  ],
  nextCursor: null,
};

const searchHits: ImportPage[] = [
  { site: 'sft.atlassian.net', id: '300', title: 'Quote domain design', parentId: null,
    hasChildren: false, updatedAt: '2026-04-01T09:00:00.000Z', version: 7, space: 'SPE' },
];

const issues: ImportJiraIssue[] = [
  { site: 'sft.atlassian.net', key: 'DIGISURE-1', summary: 'Fix the BFF',
    status: 'In Progress', project: 'DIGISURE', updatedAt: '2026-06-08T10:00:00.000+0000' },
  { site: 'sft.atlassian.net', key: 'DIGISURE-2', summary: 'Add cashback',
    status: 'To Do', project: 'DIGISURE', updatedAt: '2026-06-07T10:00:00.000+0000' },
];

const apiRequest = vi.fn();

function mockBrowseApi() {
  apiRequest.mockImplementation(async (method: string, path: string, body?: unknown) => {
    if (path === '/v1/import/confluence/spaces') return { ok: true, data: spaces };
    if (path.startsWith('/v1/import/confluence/pages')) return { ok: true, data: digPages };
    if (path.startsWith('/v1/import/confluence/search')) return { ok: true, data: searchHits };
    if (path.startsWith('/v1/import/jira/issues')) return { ok: true, data: issues };
    if (method === 'POST' && path === '/v1/import') {
      const item = (body as { items: Array<{ kind: string; key?: string; id?: string }> }).items[0]!;
      if (item.key === 'DIGISURE-2') {
        return { ok: true, data: { results: [{ kind: item.kind, key: item.key ?? null, id: item.id ?? null, ok: false, error: 'not found' }] } };
      }
      return { ok: true, data: { results: [{ kind: item.kind, key: item.key ?? null, id: item.id ?? null, ok: true, path: '20-contexts/sanlam/x.md', context: 'sanlam', updated: false, error: null }] } };
    }
    return { ok: true, data: null };
  });
}

beforeEach(() => {
  apiRequest.mockReset();
  mockBrowseApi();
  window.gb.api.request = apiRequest as typeof window.gb.api.request;
  useNavigation.setState({ active: 'import' });
});

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe('ImportScreen', () => {
  it('lists monitored spaces, expands one to its pages, and ticking shows the selection bar', async () => {
    render(wrap(<ImportScreen />));
    expect(await screen.findByText('Digisure')).toBeInTheDocument();
    expect(screen.getByText('Short-term')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'toggle space DIG' }));
    expect(await screen.findByText('ASCP architecture')).toBeInTheDocument();
    expect(screen.getByText('Runbooks')).toBeInTheDocument();
    // only the page with children gets an expand affordance
    expect(screen.getByRole('button', { name: 'expand ASCP architecture' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'expand Runbooks' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('checkbox', { name: 'select ASCP architecture' }));
    expect(screen.getByRole('button', { name: 'import 1 selected' })).toBeInTheDocument();
  });

  it('a confluence search replaces the space list with results', async () => {
    render(wrap(<ImportScreen />));
    await screen.findByText('Digisure');
    fireEvent.change(screen.getByPlaceholderText('search pages by title…'), {
      target: { value: 'quote' },
    });
    expect(await screen.findByText('Quote domain design')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'toggle space DIG' })).not.toBeInTheDocument();
    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/import/confluence/search?q=quote'),
    );
  });

  it('the jira tab lists my issues by default', async () => {
    render(wrap(<ImportScreen />));
    fireEvent.click(screen.getByRole('button', { name: 'jira' }));
    expect(await screen.findByText('DIGISURE-1')).toBeInTheDocument();
    expect(screen.getByText('Fix the BFF')).toBeInTheDocument();
    expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/import/jira/issues');
  });

  it('imports the selection one item at a time, marks results, and keeps failed items ticked', async () => {
    render(wrap(<ImportScreen />));
    fireEvent.click(screen.getByRole('button', { name: 'jira' }));
    await screen.findByText('DIGISURE-1');
    fireEvent.click(screen.getByRole('checkbox', { name: 'select DIGISURE-1' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'select DIGISURE-2' }));
    fireEvent.click(screen.getByRole('button', { name: 'import 2 selected' }));

    expect(await screen.findByText('imported')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();

    const posts = apiRequest.mock.calls.filter(([m]) => m === 'POST');
    expect(posts).toHaveLength(2);
    expect(posts[0]![2]).toEqual({
      items: [{ kind: 'jira_issue', site: 'sft.atlassian.net', key: 'DIGISURE-1' }],
    });
    expect(posts[1]![2]).toEqual({
      items: [{ kind: 'jira_issue', site: 'sft.atlassian.net', key: 'DIGISURE-2' }],
    });

    // success unticked; failure stays ticked for retry
    expect(screen.getByRole('checkbox', { name: 'select DIGISURE-1' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'select DIGISURE-2' })).toBeChecked();
    expect(screen.getByRole('button', { name: 'import 1 selected' })).toBeInTheDocument();
  });

  it('renders a connectors call-to-action on 409 instead of an error panel', async () => {
    apiRequest.mockImplementation(async (_m: string, path: string) => {
      if (path === '/v1/import/confluence/spaces') {
        return {
          ok: false,
          error: 'confluence connector not configured — run onboarding',
          status: 409,
        };
      }
      return { ok: true, data: [] };
    });
    render(wrap(<ImportScreen />));
    expect(await screen.findByText(/not connected yet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'open connectors' }));
    expect(useNavigation.getState().active).toBe('connectors');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd desktop && npx vitest run src/renderer/__tests__/ImportScreen.test.tsx
```
Expected: FAIL — `../screens/import` does not exist.

- [ ] **Step 3: Implement the screen**

Create `desktop/src/renderer/screens/import.tsx`:

```tsx
import { useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';
import { SkeletonRows } from '../components/SkeletonRows';
import { ApiError } from '../lib/api/client';
import {
  useConfluencePages,
  useConfluenceSearch,
  useImportItems,
  useImportSpaces,
  useJiraIssues,
} from '../lib/api/hooks';
import { useNavigation } from '../stores/navigation';
import { toast } from '../stores/toast';
import type {
  ImportItem,
  ImportItemResult,
  ImportJiraIssue,
  ImportPage,
  ImportSpace,
} from '../../shared/api-types';

type ImportTab = 'confluence' | 'jira';

export function selectionKey(item: ImportItem): string {
  return `${item.kind}:${item.site}:${item.id ?? item.key ?? ''}`;
}

function isNotConfigured(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

function errMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

// Same chip styling as the capture screen's source filter strip.
function tabClass(active: boolean): string {
  return `cursor-pointer rounded-sm border px-[10px] py-1 font-mono text-11 ${
    active
      ? 'border-neon/30 bg-neon/15 text-neon-ink'
      : 'border-hairline-2 bg-transparent text-ink-1'
  }`;
}

interface BrowseProps {
  query: string;
  selection: Map<string, ImportItem>;
  marks: Record<string, ImportItemResult>;
  onToggle: (item: ImportItem) => void;
}

export function ImportScreen() {
  const [tab, setTab] = useState<ImportTab>('confluence');
  const [confluenceQuery, setConfluenceQuery] = useState('');
  const [jiraQuery, setJiraQuery] = useState('');
  const [selection, setSelection] = useState<Map<string, ImportItem>>(new Map());
  const [progress, setProgress] = useState<string | null>(null);
  const [marks, setMarks] = useState<Record<string, ImportItemResult>>({});
  const importer = useImportItems();

  const query = tab === 'confluence' ? confluenceQuery : jiraQuery;
  const setQuery = tab === 'confluence' ? setConfluenceQuery : setJiraQuery;

  const toggle = (item: ImportItem) => {
    setSelection((prev) => {
      const next = new Map(prev);
      const key = selectionKey(item);
      if (next.has(key)) next.delete(key);
      else next.set(key, item);
      return next;
    });
  };

  const runImport = () => {
    const items = [...selection.values()];
    if (items.length === 0) return;
    setMarks({});
    importer.mutate(
      {
        items,
        onItem: (done, total, current) =>
          setProgress(`${done + 1}/${total} — importing ${current.key ?? current.id}…`),
      },
      {
        onSuccess: ({ results }) => {
          // The mutation posts items in order, one per request, so
          // results[i] belongs to items[i].
          const nextMarks: Record<string, ImportItemResult> = {};
          const keep = new Map<string, ImportItem>();
          results.forEach((result, i) => {
            const item = items[i]!;
            const key = selectionKey(item);
            nextMarks[key] = result;
            if (!result.ok) keep.set(key, item); // failed stays ticked for retry
          });
          setMarks(nextMarks);
          setSelection(keep);
          const failed = results.filter((r) => !r.ok).length;
          const okCount = results.length - failed;
          if (failed > 0) toast.error(`imported ${okCount} · ${failed} failed`);
          else toast.success(`imported ${okCount}`);
        },
        onError: (err) => toast.error(errMessage(err, 'import failed')),
        onSettled: () => setProgress(null),
      },
    );
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar title="import" subtitle="pull confluence pages + jira issues into the vault" />

      {/* tab strip + search */}
      <div className="flex flex-shrink-0 items-center gap-[6px] border-b border-hairline px-6 py-3">
        <button type="button" onClick={() => setTab('confluence')} className={tabClass(tab === 'confluence')}>
          confluence
        </button>
        <button type="button" onClick={() => setTab('jira')} className={tabClass(tab === 'jira')}>
          jira
        </button>
        <div className="ml-3 flex flex-1 items-center gap-2 rounded-r6 border border-hairline-2 bg-vellum px-3 py-[6px]">
          <Lucide name="search" size={13} color="var(--ink-2)" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={tab === 'confluence' ? 'search pages by title…' : 'search issues…'}
            className="flex-1 border-none bg-transparent text-13 text-ink-0 placeholder:text-ink-3 focus:outline-none"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {tab === 'confluence' ? (
          <ConfluenceBrowse query={confluenceQuery} selection={selection} marks={marks} onToggle={toggle} />
        ) : (
          <JiraBrowse query={jiraQuery} selection={selection} marks={marks} onToggle={toggle} />
        )}
      </div>

      {(selection.size > 0 || importer.isPending) && (
        <SelectionBar
          count={selection.size}
          progress={progress}
          busy={importer.isPending}
          onImport={runImport}
          onClear={() => setSelection(new Map())}
        />
      )}
    </div>
  );
}

// ── Confluence tab ──────────────────────────────────────────────────────

function ConfluenceBrowse({ query, selection, marks, onToggle }: BrowseProps) {
  const spaces = useImportSpaces();
  const searching = query.trim().length >= 2;
  const search = useConfluenceSearch(query);

  if (searching) {
    if (search.isLoading) return <SkeletonRows count={4} />;
    if (search.isError) {
      if (isNotConfigured(search.error)) return <NotConfigured connector="confluence" />;
      return (
        <PanelError
          message={errMessage(search.error, 'search failed')}
          onRetry={() => search.refetch()}
        />
      );
    }
    const hits = search.data ?? [];
    if (hits.length === 0) {
      return <PanelEmpty icon="search" message="no pages match in the monitored spaces" />;
    }
    return (
      <div className="flex flex-col gap-[2px]">
        {hits.map((page) => (
          <PageRow
            key={`${page.site}:${page.id}`}
            page={page}
            depth={0}
            expandable={false}
            selection={selection}
            marks={marks}
            onToggle={onToggle}
          />
        ))}
      </div>
    );
  }

  if (spaces.isLoading) return <SkeletonRows count={4} />;
  if (spaces.isError) {
    if (isNotConfigured(spaces.error)) return <NotConfigured connector="confluence" />;
    return (
      <PanelError
        message={errMessage(spaces.error, 'failed to load spaces')}
        onRetry={() => spaces.refetch()}
      />
    );
  }
  const rows = spaces.data ?? [];
  if (rows.length === 0) {
    return <PanelEmpty icon="inbox" message="no monitored spaces — add confluence.spaces to routing.yaml" />;
  }
  return (
    <div className="flex flex-col gap-2">
      {rows.map((space) => (
        <SpaceSection
          key={`${space.site}:${space.key}`}
          space={space}
          selection={selection}
          marks={marks}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

function SpaceSection({
  space,
  selection,
  marks,
  onToggle,
}: {
  space: ImportSpace;
  selection: Map<string, ImportItem>;
  marks: Record<string, ImportItemResult>;
  onToggle: (item: ImportItem) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-r6 border border-hairline bg-vellum">
      <button
        type="button"
        aria-label={`toggle space ${space.key}`}
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full cursor-pointer items-center gap-2 border-0 bg-transparent px-3 py-[10px] text-left"
      >
        <Lucide name={expanded ? 'chevron-down' : 'chevron-right'} size={13} color="var(--ink-2)" />
        <span className="font-mono text-11 text-ink-2">{space.key}</span>
        <span className="flex-1 text-13 font-medium text-ink-0">{space.name}</span>
        <span className="font-mono text-9 text-ink-3">→ {space.context}</span>
      </button>
      {expanded && (
        <div className="border-t border-hairline px-2 py-2">
          <PageList
            site={space.site}
            space={space.key}
            depth={0}
            selection={selection}
            marks={marks}
            onToggle={onToggle}
          />
        </div>
      )}
    </div>
  );
}

function PageList({
  site,
  space,
  parent,
  depth,
  selection,
  marks,
  onToggle,
}: {
  site: string;
  space: string;
  parent?: string;
  depth: number;
  selection: Map<string, ImportItem>;
  marks: Record<string, ImportItemResult>;
  onToggle: (item: ImportItem) => void;
}) {
  const pages = useConfluencePages(site, space, parent);
  if (pages.isLoading) return <SkeletonRows count={2} height={24} />;
  if (pages.isError) {
    return (
      <PanelError
        message={errMessage(pages.error, 'failed to load pages')}
        onRetry={() => pages.refetch()}
      />
    );
  }
  const items = pages.data?.items ?? [];
  if (items.length === 0) {
    return <p className="m-0 px-2 py-1 text-11 text-ink-3">no pages</p>;
  }
  return (
    <div className="flex flex-col gap-[2px]">
      {items.map((page) => (
        <PageRow
          key={page.id}
          page={page}
          depth={depth}
          expandable
          selection={selection}
          marks={marks}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

function PageRow({
  page,
  depth,
  expandable,
  selection,
  marks,
  onToggle,
}: {
  page: ImportPage;
  depth: number;
  expandable: boolean;
  selection: Map<string, ImportItem>;
  marks: Record<string, ImportItemResult>;
  onToggle: (item: ImportItem) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const item: ImportItem = { kind: 'confluence_page', site: page.site, id: page.id };
  const key = selectionKey(item);
  const canExpand = expandable && page.hasChildren;
  return (
    <div>
      <div
        className="flex items-center gap-2 rounded-sm px-[6px] py-[5px] hover:bg-vellum"
        style={{ paddingLeft: 6 + depth * 18 }}
      >
        {canExpand ? (
          <button
            type="button"
            aria-label={`${expanded ? 'collapse' : 'expand'} ${page.title}`}
            onClick={() => setExpanded((v) => !v)}
            className="cursor-pointer border-0 bg-transparent p-0"
          >
            <Lucide name={expanded ? 'chevron-down' : 'chevron-right'} size={12} color="var(--ink-2)" />
          </button>
        ) : (
          <span className="inline-block w-3 flex-shrink-0" />
        )}
        <input
          type="checkbox"
          aria-label={`select ${page.title}`}
          checked={selection.has(key)}
          onChange={() => onToggle(item)}
          className="h-[13px] w-[13px] cursor-pointer accent-[var(--neon)]"
        />
        <span className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-12 text-ink-0">
          {page.title}
        </span>
        {page.space && <span className="font-mono text-9 text-ink-3">{page.space}</span>}
        <ResultMark mark={marks[key]} />
        <span className="font-mono text-9 text-ink-3">{page.updatedAt?.slice(0, 10) ?? ''}</span>
      </div>
      {expanded && page.space && (
        <PageList
          site={page.site}
          space={page.space}
          parent={page.id}
          depth={depth + 1}
          selection={selection}
          marks={marks}
          onToggle={onToggle}
        />
      )}
    </div>
  );
}

// ── Jira tab ────────────────────────────────────────────────────────────

function JiraBrowse({ query, selection, marks, onToggle }: BrowseProps) {
  const issues = useJiraIssues(query);
  if (issues.isLoading) return <SkeletonRows count={4} />;
  if (issues.isError) {
    if (isNotConfigured(issues.error)) return <NotConfigured connector="jira" />;
    return (
      <PanelError
        message={errMessage(issues.error, 'failed to load issues')}
        onRetry={() => issues.refetch()}
      />
    );
  }
  const rows = issues.data ?? [];
  if (rows.length === 0) {
    return <PanelEmpty icon="search" message="no issues found" />;
  }
  return (
    <div className="flex flex-col gap-[2px]">
      {rows.map((issue) => (
        <IssueRow
          key={`${issue.site}:${issue.key}`}
          issue={issue}
          selection={selection}
          marks={marks}
          onToggle={onToggle}
        />
      ))}
    </div>
  );
}

function IssueRow({
  issue,
  selection,
  marks,
  onToggle,
}: {
  issue: ImportJiraIssue;
  selection: Map<string, ImportItem>;
  marks: Record<string, ImportItemResult>;
  onToggle: (item: ImportItem) => void;
}) {
  const item: ImportItem = { kind: 'jira_issue', site: issue.site, key: issue.key };
  const key = selectionKey(item);
  return (
    <div className="flex items-center gap-2 rounded-sm px-[6px] py-[5px] hover:bg-vellum">
      <input
        type="checkbox"
        aria-label={`select ${issue.key}`}
        checked={selection.has(key)}
        onChange={() => onToggle(item)}
        className="h-[13px] w-[13px] cursor-pointer accent-[var(--neon)]"
      />
      <span className="font-mono text-11 text-neon-ink">{issue.key}</span>
      <span className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-12 text-ink-0">
        {issue.summary}
      </span>
      <ResultMark mark={marks[key]} />
      {issue.status && <span className="font-mono text-9 text-ink-3">{issue.status}</span>}
    </div>
  );
}

// ── Shared bits ─────────────────────────────────────────────────────────

function ResultMark({ mark }: { mark?: ImportItemResult }) {
  if (!mark) return null;
  if (mark.ok) {
    return (
      <span className="font-mono text-9 text-neon-ink" title={mark.path ?? undefined}>
        {mark.updated ? 'updated' : 'imported'}
      </span>
    );
  }
  return (
    <span className="font-mono text-9 text-oxblood" title={mark.error ?? undefined}>
      failed
    </span>
  );
}

function NotConfigured({ connector }: { connector: string }) {
  const setActive = useNavigation((s) => s.setActive);
  return (
    <PanelEmpty
      icon="plug"
      message={`${connector} is not connected yet — set it up to browse and import`}
      cta={{ label: 'open connectors', onClick: () => setActive('connectors') }}
    />
  );
}

function SelectionBar({
  count,
  progress,
  busy,
  onImport,
  onClear,
}: {
  count: number;
  progress: string | null;
  busy: boolean;
  onImport: () => void;
  onClear: () => void;
}) {
  return (
    <div className="flex flex-shrink-0 items-center gap-3 border-t border-hairline bg-vellum px-6 py-3">
      <span className="font-mono text-11 text-ink-1">
        {progress ?? `${count} selected`}
      </span>
      <div className="flex-1" />
      <Btn variant="ghost" size="sm" onClick={onClear} disabled={busy}>
        clear
      </Btn>
      <Btn
        variant="primary"
        size="sm"
        icon={<Lucide name="download" size={13} />}
        onClick={onImport}
        disabled={busy || count === 0}
      >
        import {count} selected
      </Btn>
    </div>
  );
}
```

- [ ] **Step 4: Wire navigation, sidebar, and App**

Edit `desktop/src/renderer/stores/navigation.ts` — extend the union (after `'connectors'`):

```typescript
export type ScreenId =
  | 'today'
  | 'activity'
  | 'connectors'
  | 'import'
  | 'meetings'
  | 'capture'
  | 'vault'
  | 'daily'
  | 'setup'
  | 'settings';
```

Edit `desktop/src/renderer/components/Sidebar.tsx` — in `NAV_ITEMS`, insert directly after the `connectors` entry (spec: icon `download`, after connectors):

```typescript
  { id: 'import', icon: 'download', label: 'import' },
```

Edit `desktop/src/renderer/App.tsx`:

1. Add the import next to the other screens:
   ```typescript
   import { ImportScreen } from './screens/import';
   ```
2. In the screen conditionals, after `{active === 'connectors' && <ConnectorsScreen />}` add:
   ```typescript
   {active === 'import' && <ImportScreen />}
   ```

- [ ] **Step 5: Extend the App test**

In `desktop/src/renderer/__tests__/App.test.tsx`, add inside the `describe('App', …)` block (after the activity navigation test):

```tsx
  it('navigates to the import screen from the sidebar', async () => {
    wrap();
    fireEvent.click(await screen.findByRole('button', { name: 'import' }));
    expect(
      await screen.findByRole('heading', { name: 'import', level: 1 }),
    ).toBeInTheDocument();
  });
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd desktop && npx vitest run src/renderer/__tests__/ImportScreen.test.tsx src/renderer/__tests__/App.test.tsx
```
Expected: PASS — 5 screen tests + 3 App tests green.

```bash
cd desktop && npx vitest run && npm run typecheck
```
Expected: **51 passed** (45 + 5 screen + 1 new App test), typecheck clean.

- [ ] **Step 7: Commit**

```bash
git add desktop/src/renderer/screens/import.tsx \
        desktop/src/renderer/stores/navigation.ts \
        desktop/src/renderer/components/Sidebar.tsx \
        desktop/src/renderer/App.tsx \
        desktop/src/renderer/__tests__/ImportScreen.test.tsx \
        desktop/src/renderer/__tests__/App.test.tsx
git commit -m "feat(desktop): import screen — tabs, checkbox lists, search, selection bar, progress"
```

---

## Task 7: Full regression gate

No new code — every suite the feature touches must be green before the manual E2E.

- [ ] **Step 1: Backend API suite**

From the worktree root:
```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/ -q
```
Expected: **87 passed** (57 baseline + 11 repo browse + 7 import_items + 12 routes).

- [ ] **Step 2: Connector + worker suites (the refactor-safety net)**

```bash
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest \
  tests/test_atlassian_import_refactor.py \
  tests/test_confluence_connector.py tests/test_jira_connector.py \
  tests/test_pipeline.py tests/test_note_generator.py tests/test_router.py -q
```
Expected: all green, including the **5 golden tests unmodified since their pre-refactor commit** (verify with `git log --oneline -- tests/test_atlassian_import_refactor.py` — the pinned literals were committed before the refactor commit and only the Step-6 equivalence tests were appended after).

- [ ] **Step 3: Desktop suite + typecheck**

```bash
cd desktop && npx vitest run && npm run typecheck
```
Expected: **51 passed** (37 baseline + 8 hooks + 5 screen + 1 App), typecheck clean.

---

## Task 8: Manual end-to-end with real Atlassian credentials

Real credentials live on this machine (`ATLASSIAN_EMAIL` + `ATLASSIAN_TOKEN[_SFT]` via the sidecar's env loading; the scheduled confluence/jira connectors already sync). Verify the whole feature against the real vault, then clean up the test imports.

- [ ] **Step 1: Boot the sidecar against the real vault**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/feat-activity-and-import
/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m ghostbrain.api
```
Expected: `READY port=<PORT> token=<TOKEN> scheduler=off`. Note PORT and TOKEN; export them in a second terminal: `PORT=…; TOKEN=…`.

- [ ] **Step 2: Browse — spaces, pages, search, issues**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:$PORT/v1/import/confluence/spaces" | python3 -m json.tool
```
Expected: the three monitored spaces (`DIG`, `SFTHome`, `SPE`), each with `site: sft.atlassian.net`, `siteSlug: sft`, real display names, `context: sanlam`.

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:$PORT/v1/import/confluence/pages?site=sft.atlassian.net&space=DIG&limit=10" \
  | python3 -m json.tool | head -40
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:$PORT/v1/import/confluence/search?q=architecture" \
  | python3 -m json.tool | head -40
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:$PORT/v1/import/jira/issues" | python3 -m json.tool | head -40
```
Expected: top-level DIG pages with `hasChildren` flags; title-search hits with `space`; my-issues newest-first with real keys.

- [ ] **Step 3: Import ONE real page + ONE real jira issue**

Pick from Step 2 a page and an issue that are **old** (not updated in the last 24h, so the scheduled sync has never written them — the response should come back `"updated": false`, which is also what makes them safe to delete afterwards). Substitute the real id/key:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"items": [
        {"kind": "confluence_page", "site": "sft.atlassian.net", "id": "<PAGE_ID>"},
        {"kind": "jira_issue", "site": "sft.atlassian.net", "key": "<ISSUE-KEY>"}
      ]}' \
  "http://127.0.0.1:$PORT/v1/import" | python3 -m json.tool
```
Expected: both results `"ok": true`, `"context": "sanlam"`, `"updated": false`, paths under `20-contexts/sanlam/confluence/` and `20-contexts/sanlam/jira/tickets/`.

- [ ] **Step 4: Verify vault files, audit, and heatmap**

```bash
head -30 ~/ghostbrain/vault/<CONFLUENCE_PATH_FROM_RESPONSE>
head -30 ~/ghostbrain/vault/<JIRA_PATH_FROM_RESPONSE>
grep import_completed ~/ghostbrain/vault/90-meta/audit/$(date +%F).jsonl
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:$PORT/v1/activity/heatmap?days=7" | python3 -m json.tool
```
Expected: frontmatter identical in shape to scheduled-sync notes (compare with a neighbour file in the same dir: `id`/`sourceId` like `confluence:sft:<id>`, `routingMethod: path`, `space`/`key` keys present); two `import_completed` audit lines with `"ok": true` and `source` `confluence`/`jira`; today's heatmap entry's `bySource` includes `confluence` and `jira` counts (the import shows up as activity).

- [ ] **Step 5: Visual check in the app**

```bash
cd desktop && npm run dev
```
Checklist:
- Sidebar shows "import" (download icon) directly under "connectors"; the row highlights when active.
- Confluence tab: the three monitored spaces as expandable sections; expanding shows top-level pages; pages with children expand further; typing 2+ chars in the search box swaps in title-search results; clearing restores the spaces.
- Jira tab: my-issues list; typing a query swaps in text-search results.
- Tick 2–3 items across both tabs → selection bar appears ("N selected", primary "import N selected" button); during import the bar shows "k/N — importing …"; afterwards rows show inline `imported`/`updated`/`failed` marks and a summary toast; failed items stay ticked.
- Re-import one of the same items → its mark reads `updated`.
- Activity screen: today's log shows "import completed" rows.
- (If reachable) temporarily renaming `ATLASSIAN_TOKEN*` in the sidecar env and restarting renders the connectors call-to-action instead of an error toast.

- [ ] **Step 6: Clean up the imported test files**

For every Step-3/Step-5 import whose result said `"updated": false` (i.e. the note did not exist before this E2E), remove both copies — the context note and its inbox twin share the same filename:

```bash
BASENAME=$(basename "<CONFLUENCE_PATH_FROM_RESPONSE>")
rm ~/ghostbrain/vault/<CONFLUENCE_PATH_FROM_RESPONSE> \
   ~/ghostbrain/vault/00-inbox/raw/confluence/$BASENAME
BASENAME=$(basename "<JIRA_PATH_FROM_RESPONSE>")
rm ~/ghostbrain/vault/<JIRA_PATH_FROM_RESPONSE> \
   ~/ghostbrain/vault/00-inbox/raw/jira/$BASENAME
```
Do **not** delete anything that came back `"updated": true` — that overwrote a pre-existing note the user already had. The `import_completed` audit lines stay (they are an accurate record). Stop the sidecar (Ctrl-C).

- [ ] **Step 7: Record the E2E pass in the spec**

Append at the bottom of `docs/superpowers/specs/2026-06-10-atlassian-import-design.md`:

```markdown
## Implementation status

- 2026-06-XX: E2E pass — browse (spaces/pages/search/issues) verified against
  sft.atlassian.net; imported 1 real Confluence page + 1 real Jira issue
  (path-routed to sanlam, connector-identical frontmatter, `updated: false`);
  re-import returned `updated: true`; `import_completed` audit lines present
  and visible in the activity heatmap (`bySource.confluence`/`bySource.jira`);
  full tab/select/progress/toast flow verified visually; imported test files
  deleted afterwards.
```

```bash
git add docs/superpowers/specs/2026-06-10-atlassian-import-design.md
git commit -m "docs(spec): record atlassian import E2E pass"
```

---

## Self-Review Notes

After writing this plan, I checked it against the spec and the actual code on this branch:

**Coverage:** Spec "Browse endpoints" table → Task 2 (repo) + Task 4 (routes): spaces from routing.yaml with `{site, siteSlug, key, name, context}`; pages with `site/space/parent/limit/cursor` and `{id, title, parentId, hasChildren, updatedAt, version}` rows; search via CQL `title ~ q` across monitored spaces (+ `space` on rows); jira my-issues JQL default / `text ~ q` with `{site, key, summary, status, project, updatedAt}`. 409 with the spec's exact detail string on missing config OR missing auth → decisions 5. Spec "Import endpoint" → Tasks 3–4: max 50 (422 via pydantic), sequential processing, fetch→convert (same truncation — `normalize_page` is the connector's own code)→persist (connector naming via `write_note`)→inline routing (`process_event`), per-item results with `updated` flag, failure isolation, one `import_completed` audit line per item (ok and failed). Spec "Desktop" → Tasks 5–6: `'import'` ScreenId + sidebar `download` icon after connectors; two tabs; search inputs; expandable space→pages→children checkbox lists; jira my-issues with search replacing the list; selection bar with primary import button, per-item progress text, summary toast, inline result marks, failed-stays-ticked; 409 call-to-action linking to the connectors screen; all five hooks (`useImportSpaces`, `useConfluencePages`, `useConfluenceSearch`, `useJiraIssues`, `useImportItems` with captures+activity invalidation). Spec "Error handling" → per-item shape (Task 3), browse `PanelError` with retry (Task 6), mutation errors → toast not throw-across-IPC (the IPC bridge already returns `ApiResult`; `ApiError` is renderer-side only), routing falls back exactly like syncs because it IS the sync code path. Spec "Testing" → every backend behaviour it lists has a named test in Tasks 2–4 (including the golden refactor-safety test, Task 1); renderer flows in Task 6.

**Codebase contradictions found (and how the plan resolves them):**
1. **"Stable pageId/issue-key naming" is not how notes are named.** `_filename_for` embeds the event timestamp and title; the id suffix is degenerate (`confluencesf` for every Confluence note — verified in the real vault). Resolution: dedup by frontmatter `id` with stale-copy removal (`_existing_note_paths`), keeping the connector naming byte-identical. Tested by `test_reimport_unchanged_page_overwrites_same_path_updated_true` and `test_reimport_changed_page_removes_stale_note`.
2. **Connectors don't route or persist — they enqueue.** `notes_manual.py` does not exist on this branch; the persist+route machinery is `worker/pipeline.process_event` (router + `write_note`), which the worker calls on dequeued events. Import calls it inline; `test_import_output_identical_to_scheduled_sync` proves byte-equality (modulo `ingestedAt`) against the actual connector→pipeline path.
3. **Context copies only exist in `routing_mode: live`** (the user's real config). Tests pin that with `write_live_config`; in `review_only` the result `path` would be the inbox path — same response shape, documented in `import_items`' docstring.
4. **No tab pattern exists in the desktop app**; the spec's "house tab pattern" maps to the capture screen's chip strip, reused verbatim (`tabClass`).
5. **The renderer drops HTTP status** (`client.ts` threw plain `Error`); the forwarder already supplies it. `ApiError extends Error` is the smallest change that makes the 409 CTA possible without breaking existing `instanceof Error` checks.

**Type consistency:** `ImportSpace`/`ImportPage`/`ConfluencePagesResponse`/`ImportJiraIssue`/`ImportItem(Request)`/`ImportItemResult`/`ImportResponse` in `desktop/src/shared/api-types.ts` (Task 5) mirror `ghostbrain/api/models/import_atlassian.py` (Task 2), which mirror the dict literals produced by the repo (Tasks 2–3). `useImportItems`'s `ImportRunVars.onItem(done, total, current)` signature is identical in the hook (Task 5), its test, and the screen's `runImport` (Task 6). `selectionKey` is the single key derivation shared by the screen's selection map, marks record, and tests. `ScreenId` gains exactly one member, `'import'`, consumed by Sidebar/App/NotConfigured.

**Counts:** backend 57 → 68 (Task 2) → 75 (Task 3) → 87 (Task 4); connector suite 12 → 17 (Task 1); desktop 37 → 45 (Task 5) → 51 (Task 6).

**Known seams (deliberate, small):**
- The golden test's `body` literal depends on markdownify's exact output; the plan instructs pinning the observed literal *before* the refactor commit, preserving the characterization property.
- Confluence v1 endpoints (`/space/{key}/content/page?depth=root`, `/content/{id}/child/page`) match the connector's v1 usage; if Atlassian retires them the browse repo is the only place to swap in v2, and the manual E2E (Task 8 Step 2) is the canary.
- `useImportItems` sends sequential 1-item batches (decision 4); the bulk endpoint contract (≤50, per-item results) is still exercised end-to-end by `test_post_import_happy_path_writes_note` with a 2-item batch.

**No placeholders:** every step has complete runnable code or an exact command with its expected outcome.
