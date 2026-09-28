# Gmail Backfill — Design

**Status:** Approved in conversation 2026-09-28
**Origin:** The user connected Gmail (v1.7/1.8 multi-account) and wants past mail indexed — about
3 years back — not just the daily sync's unread-in-the-last-24h window.

## Decisions (from the conversation)

- **What:** threads the user took part in — `from:me OR is:starred OR is:important` — minus
  Gmail Promotions and the configured `gmail.denylist_domains`.
- **Processing:** no relevance gate (participation = relevant); routing as usual — specific
  rules → account context → LLM. Notes identical to daily-sync notes; dedup by note id.
- **Where:** a "backfill…" action on each Gmail account row in the Gmail connector's detail
  panel (the accounts block from v1.8.0). Core feature — not a plugin (plugins can't reach the
  sidecar's Gmail tokens).
- **How:** a resumable job driven by the in-app scheduler, one small batch per tick, state in a
  per-account file.

## Non-goals

- Backfilling Outlook, Slack, Jira or other connectors.
- Attachments beyond what the daily sync already captures.
- Custom Gmail queries or per-label backfills.
- Running without the in-app scheduler.

## Design

### 1. Job + state — `ghostbrain/connectors/gmail/backfill.py`

State file per account: `<state>/gmail_backfill.<slug>.json` (slug as in
`gmail.auth.token_path`):

```json
{"account": "you@example.com", "status": "running", "since": "2023-09-28",
 "cursor": "2026-09", "pageToken": null, "imported": 0, "skipped": 0, "failed": 0,
 "error": null, "startedAt": "…", "updatedAt": "…"}
```

- `status`: `running | paused | done | error`. `cursor`: the month being processed
  (`YYYY-MM`), starting at the current month and moving backwards; `done` once the cursor month
  ends before `since`.
- Public API:
  - `start(account, *, since: date) -> dict` — create (or return the existing non-done) state;
    `since` is clamped to at most 10 years back.
  - `get(account) -> dict | None` (adds `monthsTotal`, `monthsDone`),
    `pause(account)`, `resume(account)` (also clears `error`), `cancel(account)` (deletes the
    state file; imported notes stay).
  - `estimate(account, *, since: date) -> int` — Gmail `resultSizeEstimate` for the whole range.
  - `run_tick(*, batch_size=25) -> dict` — process one batch for ONE running backfill (round-robin
    by oldest `updatedAt`); returns a summary.
- Query per month: `(from:me OR is:starred OR is:important) -category:promotions after:YYYY/MM/01 before:YYYY/MM/01(next)`.
- Per tick: list up to `batch_size` thread stubs for the cursor month from `pageToken`; build the
  set of existing Gmail note ids ONCE (scan `00-inbox/raw/gmail/*.md` and
  `20-contexts/*/gmail/**/*.md` frontmatter ids); for each thread: fetch full, `_normalize_thread`
  (adds `metadata.accountId`), drop if `_is_denied` (denylist from routing.yaml) or
  `_is_promotional`, skip if its id exists (`skipped`), else `worker.pipeline.process_event(event)`
  (`imported`); per-thread exceptions → `failed` + log; persist state after every thread.
  Page exhausted → cursor to previous month, `pageToken` null. Cursor before `since` → `done`.
- `GmailAuthError` → `status: error`, `error: "needs re-auth"`, stop the tick; nothing is lost.
- Account removed from the registry → cancel (delete state). Account disabled → skip (acts as
  paused) until re-enabled.
- The daily sync is unchanged (relevance gate still on for it).

### 2. Scheduler job

`scheduler_jobs.register_connectors` adds `gmail-backfill` every 120 s → `_wrap_job("gmail-backfill",
lambda: backfill.run_tick())`. With no running backfill the tick returns `{"skipped": "idle"}`
immediately.

### 3. API — `ghostbrain/api/routes/connectors.py`

| Method | Path | Body | Result |
|---|---|---|---|
| GET | `/v1/connectors/gmail/accounts/{id}/backfill` | — | state + `monthsTotal`/`monthsDone`, or 404 |
| GET | `/v1/connectors/gmail/accounts/{id}/backfill/estimate?years=N` | — | `{"threads": int, "since": "YYYY-MM-DD"}` |
| POST | `/v1/connectors/gmail/accounts/{id}/backfill` | `{"years": 1-10}` | 201 + state; 409 if the in-app scheduler is off |
| POST | `…/backfill/pause`, `…/backfill/resume` | — | state; 404 if none |
| DELETE | `…/backfill` | — | `{"ok": true}` |

Unknown Gmail account → 404. Auth errors on estimate → 409 with "needs re-auth".

### 4. UI — `ConnectorAccounts` (Gmail only)

- Row button **backfill…** → dialog: years select (1/2/3/5, default 3), estimate line
  ("~N threads you took part in · about H h at the current pace"; pace = 750 threads/hour),
  **start backfill**. Scheduler off → message + no start button.
- Active backfill → progress line under the row: running "backfilling · <Mon YYYY> · I imported ·
  S already had · F failed" + pause + cancel; paused → resume + cancel; error → "needs re-auth"
  + reauthorize (opens the auth modal) + resume; done → "backfill complete · I imported" +
  dismiss (cancel).
- Hooks: `useGmailBackfill(accountId)` (refetch every 15 s while running and the panel is
  mounted), `useStartBackfill`, `useBackfillAction` (pause/resume/cancel), `useBackfillEstimate`.

## Error handling

| Situation | Behaviour |
|---|---|
| Auth failure during a tick | status `error` "needs re-auth"; resume after reauthorize |
| One thread fails | counted in `failed`, logged, next thread |
| Crash / restart mid-page | resumes from saved cursor + pageToken; dedup skips the redone thread |
| Account removed | backfill cancelled |
| Account disabled | backfill skipped until re-enabled |
| Scheduler off | start → 409 with a clear message; UI explains |

## Testing

Job with a fake Gmail service (threads().list / get): month cursor stepping, pageToken paging,
resume after crash, dedup skip, denylist + promotions drop, auth error → error → resume, done,
cancel keeps notes, disabled/removed accounts, idle tick. Routes: 201/404/409, estimate, pause/
resume/cancel. UI: dialog + estimate, progress states, action calls.
