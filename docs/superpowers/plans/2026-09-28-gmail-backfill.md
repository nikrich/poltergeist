# Gmail Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Backfill years of Gmail threads the user took part in, per account, via a resumable scheduler-driven job with progress/pause/resume in the connector panel.

**Architecture:** `ghostbrain/connectors/gmail/backfill.py` holds per-account state files and a `run_tick()` that processes one small batch per scheduler tick through the existing `worker.pipeline.process_event`; thin API routes expose start/status/pause/resume/cancel/estimate; the desktop `ConnectorAccounts` block gains a backfill dialog and progress line for Gmail rows.

**Tech Stack:** Python 3.11, googleapiclient (mocked in tests), FastAPI, pytest; React/TS/TanStack Query/vitest.

**Spec:** `docs/superpowers/specs/2026-09-28-gmail-backfill-design.md`

## Global Constraints

- Worktree `/Users/jannik/development/nikrich/ghost-brain-account-ui`, branch `feat/gmail-backfill`. Every shell command starts with `cd /Users/jannik/development/nikrich/ghost-brain-account-ui && `. Verify the branch before committing.
- Safety: never read/write the real `~/ghostbrain`, `~/.ghostbrain`, `~/.claude`; never run the app, CLIs, gh, Google APIs or network; no `git stash`; don't touch other worktrees.
- Python: `.venv/bin/python -m pytest <path> -q -p no:cacheprovider`; full suite `... --ignore=tests/test_recorder_wasapi_io.py` must show only the 22 baseline failures (test_agent_stream 1, test_calendar 1, test_joplin_connector 2, test_mcp_integration 1, test_mcp_tools 2, test_recorder_api_platform_guard 1, test_recorder_audio_backend 7, test_recorder_platform_guard 2, test_semantic 4, test_weekly_digest 1).
- Desktop (`desktop/`): `npm run typecheck`, `npm test`, `npm run lint` (max-warnings 0); Windows-safe tests; mock conventions as in existing tests.
- Generic names only (`tests/test_no_hardcoded_contexts.py`). Ruff clean on added lines. Commit trailer: your own session's attribution line.
- Exact values: batch 25 threads/tick, tick every 120 s, pace shown as 750 threads/hour, years 1–10 (UI offers 1/2/3/5, default 3), query `(from:me OR is:starred OR is:important) -category:promotions`, state file `<state>/gmail_backfill.<slug>.json`, statuses `running|paused|done|error`, auth error message `needs re-auth`.

## Review Focus

1. **Restart mid-page** — resumes from cursor+pageToken and never double-writes a note. Test: Task 1 `test_resume_after_crash_mid_page`.
2. **Mailbox with an empty month** — cursor steps past it. Test: Task 1 `test_empty_month_steps_back`.
3. **Thread already captured by the daily sync** — skipped, counted as `skipped`. Test: Task 1.
4. **Token expires mid-backfill** — `error` + resume works after re-auth. Test: Task 1.
5. **Two accounts backfilling** — ticks alternate (oldest `updatedAt` first). Test: Task 1.

---

### Task 1: Backfill job + state

**Files:** Create `ghostbrain/connectors/gmail/backfill.py`, `tests/test_gmail_backfill.py`.

**Interfaces — Consumes:** `gmail.auth.token_path(email)` (slug), `gmail.auth.load_credentials`, `GmailAuthError`; `gmail.connector._normalize_thread(thread, account=...)`, `_is_denied(event, denylist)`, `_is_promotional(event)`; `accounts.get_account("gmail", id)`; `worker.pipeline.process_event(event)`; `paths.state_dir()`, `paths.vault_path()`. **Produces:** `start(account: str, *, since: date) -> dict`, `get(account) -> dict | None`, `pause(account) -> dict | None`, `resume(account) -> dict | None`, `cancel(account) -> bool`, `estimate(account, *, since: date) -> int`, `run_tick(*, batch_size: int = 25, service_factory=None, process=None) -> dict`, `QUERY_BASE`, `BATCH_SIZE = 25`, `MAX_YEARS = 10`.

Implementation notes (complete behaviour — write it this way):

```python
"""Gmail backfill — index past threads the user took part in.

One state file per account at <state>/gmail_backfill.<slug>.json; the in-app
scheduler calls run_tick() every 2 minutes and each tick processes one small
batch for one running backfill, newest month first. Threads go through the
normal worker pipeline (routing: rules → account context → LLM) without the
daily sync's relevance gate. Imported notes are never removed by cancel.
"""
QUERY_BASE = "(from:me OR is:starred OR is:important) -category:promotions"
BATCH_SIZE = 25
MAX_YEARS = 10
```

- `_state_path(account)`: `state_dir() / f"gmail_backfill.{token_path(account).stem.split('.',1)[1]}.json"` — or recompute the slug the same way `token_path` does (lower, `@`→`_at_`, `.`→`_`); keep ONE helper.
- `start`: validate the account exists in the registry (`accounts.get_account("gmail", account)`) else `KeyError`; clamp `since` to ≥ today − `MAX_YEARS` years; if a state exists with status ≠ `done`, return it unchanged; else write `{"account", "status": "running", "since": iso, "cursor": today's YYYY-MM, "pageToken": None, "imported": 0, "skipped": 0, "failed": 0, "error": None, "startedAt": now, "updatedAt": now}`.
- `get`: read state (None if missing / unreadable) and add `monthsTotal` (months from `since` month to start month inclusive, computed from `startedAt`) and `monthsDone` (months from start month back to cursor, exclusive of cursor; `monthsTotal` when done).
- `pause`/`resume`: set status (`resume` also clears `error`), persist; None when no state. `cancel`: delete the file; True if it existed.
- `estimate`: one `threads().list(userId="me", q=f"{QUERY_BASE} after:{since:%Y/%m/%d}", maxResults=1)` → `resultSizeEstimate` (int, 0 when absent). Raises `GmailAuthError` through.
- `run_tick`: pick the running state with the oldest `updatedAt` whose account is enabled in the registry (missing from registry → delete its state file and continue to the next; disabled → skip). None → `{"skipped": "idle"}`. Build the service with `service_factory(account)` (default: googleapiclient `build("gmail","v1", credentials=load_credentials(account), cache_discovery=False)`). Month window: `after:YYYY/MM/01 before:<first day of next month>`. `threads().list(userId="me", q=..., maxResults=batch_size, pageToken=state["pageToken"])`. Existing ids: scan once per tick (`00-inbox/raw/gmail/*.md`, `20-contexts/*/gmail/**/*.md`, frontmatter `id`). Denylist from routing.yaml `gmail.denylist_domains`. For each stub: `threads().get(userId="me", id=..., format="full")` → `_normalize_thread(full, account=account)`; None → skipped; denied or promotional → skipped; id in existing → skipped; else `process(event)` (default `worker.pipeline.process_event`) → imported and add id to the set; any exception from get/process → failed (log with thread id, never the body); persist counts + `updatedAt` after EVERY thread. After the page: `nextPageToken` present → save it; absent → move `cursor` back one month, `pageToken` None; if the new cursor month's last day < `since` → status `done`. `GmailAuthError` anywhere → status `error`, `error: "needs re-auth"`, persist, return. Return `{"account", "status", "imported": n, "skipped": n, "failed": n, "cursor"}` for this tick.
- Atomic state writes (temp + `os.replace`); a module `threading.Lock` around read-modify-write.

Tests (`tests/test_gmail_backfill.py`) with a fake service: `FakeGmail(threads_by_month: dict["YYYY-MM", list[thread]], page_size)` implementing `users().threads().list(...).execute()` (parses `after:`/`before:` to pick the month, honours `maxResults`/`pageToken`, returns `resultSizeEstimate`) and `.get(...).execute()`; a `process` stub recording events. Use the vault fixture pattern from `tests/test_multi_account_connectors.py` (routing.yaml with contexts + `gmail.denylist_domains`, accounts.yaml with the gmail account). Required tests:
`test_start_creates_running_state_and_is_idempotent`, `test_since_clamped_to_ten_years`, `test_tick_imports_batch_and_persists_counts`, `test_paging_uses_page_token_then_steps_month_back`, `test_empty_month_steps_back`, `test_done_after_since`, `test_existing_note_skipped` (write a gmail note with `id: gmail:thread:<id>` under `20-contexts/personal/gmail/`), `test_denylisted_and_promotional_skipped`, `test_thread_error_counts_failed_and_continues`, `test_auth_error_sets_error_then_resume`, `test_resume_after_crash_mid_page` (process raises SystemExit-like interruption after 2 threads → next tick redoes nothing twice), `test_pause_makes_tick_idle`, `test_cancel_deletes_state_keeps_notes`, `test_removed_account_cancels_disabled_account_skips`, `test_two_accounts_alternate`, `test_estimate_returns_result_size`, `test_get_reports_months_progress`.

- [ ] TDD RED → implement → GREEN → full suite → ruff → commit `feat(gmail): resumable backfill job for threads you took part in`.

---

### Task 2: Scheduler job + API routes

**Files:** Modify `ghostbrain/scheduler_jobs.py` (add `gmail-backfill`, `Interval(seconds=120)`, label `"every 2m"`, fn `_gmail_backfill_job` returning `_wrap_job("gmail-backfill", lambda: backfill.run_tick())`), `ghostbrain/api/routes/connectors.py`; Test `ghostbrain/api/tests/test_gmail_backfill_routes.py`, extend the scheduler registration test if one enumerates jobs.

Routes (order: define these BEFORE the generic `/{connector_id}/accounts/{account_id}` PATCH if path matching could collide — they use distinct methods/suffixes, but keep them grouped):
- `GET /v1/connectors/gmail/accounts/{account_id}/backfill` → `backfill.get` or 404.
- `GET /v1/connectors/gmail/accounts/{account_id}/backfill/estimate?years=3` (1–10, 422 otherwise) → `{"threads": backfill.estimate(...), "since": iso}`; unknown account 404; `GmailAuthError` → 409 `"needs re-auth"`.
- `POST /v1/connectors/gmail/accounts/{account_id}/backfill` body `{"years": int 1-10}` → 409 `"Backfill needs the in-app scheduler. Enable 'Run scheduler in-app' in Settings."` when `request.app.state.scheduler` is None; unknown account 404; else 201 + `backfill.get`.
- `POST …/backfill/pause`, `POST …/backfill/resume` → state or 404. `DELETE …/backfill` → `{"ok": True}` (idempotent).
`since` = today − years (use `date.replace(year=...)`, Feb 29 → Feb 28).

Tests: each status code above with `backfill` functions monkeypatched where Gmail would be called (estimate) and the real state module otherwise; scheduler registered job name `gmail-backfill` with interval 120.

- [ ] TDD → GREEN → full suite → commit `feat(api): gmail backfill routes + scheduler tick`.

---

### Task 3: Desktop backfill UI

**Files:** Modify `desktop/src/shared/api-types.ts` (`GmailBackfill` type: account, status, since, cursor, imported, skipped, failed, error, monthsTotal, monthsDone, startedAt, updatedAt), `desktop/src/renderer/lib/api/hooks.ts` (`useGmailBackfill(accountId, enabled)` — key `['gmail-backfill', accountId]`, `refetchInterval` 15000 only while status is `running`, treat 404 as null; `useBackfillEstimate(accountId, years, enabled)`; `useStartBackfill()`; `useBackfillAction()` for pause/resume/cancel — all invalidate `['gmail-backfill', accountId]`), `desktop/src/renderer/components/ConnectorAccounts.tsx` (Gmail rows only: `connector.id === 'gmail'`), new `desktop/src/renderer/components/GmailBackfill.tsx` (dialog + progress line); Test `desktop/src/renderer/__tests__/GmailBackfill.test.tsx`.

UI exactly per spec §4: "backfill…" button → dialog (years 1/2/3/5 default 3, estimate line `~N threads you took part in · about H h at the current pace` with H = ceil(N/750), start button; 409 scheduler-off → show the server message, no start); progress line states running/paused/error/done with the listed buttons (`aria-label`s include the account id); reauthorize calls the existing `onReauth(id)`.

Tests: dialog renders estimate + posts `{years: 3}`; years change refetches estimate; running line text + pause/cancel calls; paused → resume; error → "needs re-auth" + reauthorize callback; done → dismiss sends DELETE; non-gmail connectors show no backfill button.

- [ ] TDD → `npm run typecheck && npm test && npm run lint` → commit `feat(desktop): gmail backfill dialog and progress in connector accounts`.

---

### Task 4: Docs

- `docs/connectors.md` Gmail section: "Backfilling past mail" — what's included, pace, pause/resume, needs in-app scheduler, cancel keeps imported notes, relevance gate skipped for backfill.
- Full suite + desktop gates. Commit `docs: gmail backfill`.
