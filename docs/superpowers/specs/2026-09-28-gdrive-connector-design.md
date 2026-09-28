# Google Drive Connector — Design

**Status:** Approved in conversation 2026-09-28
**Origin:** The user wants Google Drive documents in the vault — a one-off backfill of existing
docs plus continuous import of new and changed ones.

## Decisions (from the conversation)

- **Which files:** files the account **owns or has modified** (`ownedByMe || modifiedByMe`).
  Docs only shared with the user are ignored unless the user has edited them.
- **Which types:** Google Docs, Google Sheets, uploaded PDF, DOCX and XLSX. Slides, images and
  everything else are out.
- **Edits:** one note per Drive file, updated **in place** when the file changes. The note keeps
  the context it was first routed to (no re-routing LLM call on update).
- **Approach:** a single `files.list` query shape, windowed by `modifiedTime`, drives both the
  hourly sync (`modifiedTime > last_run`) and the backfill (month windows walking backwards).
  The Drive `changes` API is not used — deletions/trash are deliberately ignored, so it would
  add a second code path for nothing.
- **Backfill:** same shape as the Gmail backfill (`2026-09-28-gmail-backfill-design.md`, other
  branch): a resumable per-account job ticked by the in-app scheduler. Built independently to
  the same shape; a shared backfill base is extracted after both branches merge.
- **Size caps (raised on request):** downloads up to 200 MB, note bodies up to 1M chars, Sheets
  up to 5,000 rows × 50 columns per tab, and native Docs/Sheets are not bound by Drive's 10 MB
  export limit.
- **Core feature, not a plugin:** plugins can't reach the sidecar's Google tokens or the worker
  pipeline.

## Non-goals

- Google Slides, images, other binary types.
- Acting on deletions, trash, or permission changes (notes of trashed/deleted files stay).
- Docs merely shared with the user; per-folder or shared-drive selection.
- Comments, suggestions, revision history.
- A generic backfill framework (follow-up once Gmail backfill and this both merge).

## Design

### 1. Auth + account registry

- New package `ghostbrain/connectors/gdrive/` with `auth.py` mirroring `gmail/auth.py`:
  `SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]`, `oauth_client_path()` (shared
  `google_oauth_client.json`), `token_path(email)` → `<state>/gdrive.<slug>.token`,
  `load_credentials(email)` raising `GdriveAuthError`, `run_oauth_flow(email)`.
  `drive.readonly` also authorises read calls to the Docs and Sheets APIs.
- `accounts.py`: add `"gdrive"` to `ACCOUNT_CONNECTORS` and `SOURCE_TO_ACCOUNT_CONNECTOR`;
  accounts read from `routing.yaml` `gdrive.accounts` like Gmail.
- `api/auth/providers/google_oauth.py`: `_mod("gdrive")` returns the gdrive auth module;
  `register_all.py` registers `gdrive` on the shared `GoogleProvider`.
- `api/auth/disconnect.py`: disconnecting a gdrive account deletes its token.
- **Setup requirement:** the user's Google Cloud project must have the **Drive, Docs and
  Sheets APIs** enabled. A 403 `accessNotConfigured` is caught and surfaced as
  "Enable the <API> API in Google Cloud for your OAuth client's project" (health check +
  run error), and the onboarding skill's Google section lists all three APIs.

### 2. Fetch + filter — `gdrive/drive.py`

- Query: `trashed = false and modifiedTime > '<X>' [and modifiedTime < '<Y>'] and mimeType in
  (gdoc, gsheet, pdf, docx, xlsx)`, fields
  `id, name, mimeType, modifiedTime, size, ownedByMe, modifiedByMe, owners, webViewLink,
  parents, lastModifyingUser`, `pageSize=100`, `orderBy=modifiedTime desc`,
  `includeItemsFromAllDrives=true, supportsAllDrives=true`.
- Keep only `ownedByMe or modifiedByMe`.
- Folder path: resolve `parents` → names with a per-run cache (best-effort; `metadata.folder`
  is omitted on failure).
- Rate limits (403 `rateLimitExceeded`/`userRateLimitExceeded`, 429, 5xx): exponential backoff,
  3 retries, then raise `DriveRateLimited`.

### 3. Convert — `gdrive/convert.py`

`to_markdown(service, file) -> ConvertResult(body: str, truncated: bool, note: str | None)`:

| Type | Method |
|---|---|
| Google Doc | `files.export(mimeType="text/markdown")`. On `exportSizeLimitExceeded` (>10 MB): Docs API `documents.get` → own converter (headings, paragraphs, lists, tables, links). |
| Google Sheet | Sheets API: `spreadsheets.get(fields=sheets.properties)` for tab names, then `values.batchGet` for `'<tab>'!A1:AX5000` per tab (≤ 50 cols, ≤ 5,000 rows), `valueRenderOption=FORMATTED_VALUE`. |
| XLSX upload | download (§ size) → `openpyxl.load_workbook(read_only=True, data_only=True)`, same caps. |
| PDF / DOCX upload | download (§ size) → the existing chat-attachment extractor (`pypdf` / `python-docx`). |

- Tables (Sheets + XLSX share `render_tables(tabs)`): each tab → `## <tab>` + a Markdown
  table (first row as header, pipes escaped, newlines in cells → `<br>`); empty trailing rows
  and columns trimmed; empty tabs skipped; at most 50 tabs. Cut content ends with
  `_…truncated: N more rows_` / `_…N more columns_` / `_…N more tabs_`.
- Downloads stream via `MediaIoBaseDownload` to a temp file (never fully in memory); files with
  `size > 200 MB` are skipped as `too_large` without downloading.
- Body cap 1,000,000 chars; beyond it the body is cut at a line boundary with
  `_…truncated (document continues in Drive)_`.
- Empty extraction (image-only/encrypted PDF, empty doc) → body is
  `_No extractable text — open in Drive._`; the note is still written so it's findable.

### 4. Event shape

```python
{
  "id": "gdrive:<account-slug>:<fileId>",
  "source": "gdrive", "type": "doc" | "sheet" | "pdf" | "docx" | "xlsx", "subtype": "updated",
  "timestamp": <modifiedTime>, "title": <name>, "url": <webViewLink>,
  "actorId": "gdrive:<lastModifyingUser.emailAddress>",
  "body": <markdown>,
  "metadata": {"accountId": <email>, "fileId": ..., "mimeType": ..., "driveModifiedTime": ...,
               "owners": [...], "folder": "A/B/C", "truncated": bool},
}
```

`note_generator._context_target_dir`: `source == "gdrive"` → `20-contexts/<ctx>/gdrive/`.

### 5. Store — `gdrive/store.py` (shared by sync + backfill)

- `build_index() -> dict[event_id, (path, driveModifiedTime)]`: scan frontmatter of
  `00-inbox/raw/gdrive/**/*.md` and `20-contexts/*/gdrive/**/*.md` once per run/tick.
- `upsert(event, index) -> "imported" | "updated" | "skipped"`:
  - id unknown → `worker.pipeline.process_event(event)` (normal routing: specific rules →
    account context → LLM); record the written path in the index.
  - id known, `driveModifiedTime` newer → rewrite that note (and its inbox/context twin if both
    exist) in place: body + `driveModifiedTime` + `title`; all other frontmatter (context,
    routing fields, tags) kept. No LLM call.
  - id known, same `driveModifiedTime` → skip.
- **Stable filenames:** for `source == "gdrive"`, `_filename_for` drops the timestamp prefix →
  `<title-slug>-<id-suffix>.md`, so a new write of the same file never creates a sibling.
- Found by frontmatter id wherever it lives, so a note the user moved still gets updated.
- A per-note lock (`fcntl` where available, in-process lock otherwise) guards rewrites;
  together with the `modifiedTime` check, a concurrent sync + backfill can't double-write.

### 6. Hourly sync — `gdrive/connector.py` + `runner.py`

- `GdriveConnector(Connector)`, one instance over all enabled gdrive accounts (per-account
  health via `accounts_health`, as Gmail does); `run()` overridden to use `store.upsert`
  instead of the queue so updates go through the in-place path.
- Window: `modifiedTime > last_run` (first run with no `last_run`: last 7 days — history is the
  backfill's job).
- **Debounce:** files with `modifiedTime` within the last 30 min are deferred; `last_run` is
  saved as `min(now, oldest deferred modifiedTime)` so they're picked up next run.
- `DriveRateLimited` or all accounts failing → `last_run` not saved.
- Scheduler: `gdrive` every 1 h (`scheduler_jobs.register_connectors`).

### 7. Backfill — `gdrive/backfill.py`

State per account: `<state>/gdrive_backfill.<slug>.json`

```json
{"account": "you@example.com", "status": "running", "since": "2023-09-28",
 "cursor": "2026-09", "pageToken": null, "imported": 0, "updated": 0, "skipped": 0,
 "failed": 0, "tooLarge": 0, "error": null, "startedAt": "…", "updatedAt": "…"}
```

- `status`: `running | paused | done | error`; `cursor` starts at the current month and walks
  back; `done` when the cursor month ends before `since` (clamped to ≤ 10 years back).
- API: `start(account, *, since)`, `get(account)` (+ `monthsTotal`, `monthsDone`), `pause`,
  `resume` (clears `error`), `cancel` (deletes state; notes stay),
  `estimate(account, *, since) -> {"files": int, "capped": bool}` (pages `files(id, ownedByMe,
  modifiedByMe)` only; stops at 5,000 → shown as "5,000+"),
  `run_tick(*, batch_size=25)` — one batch for ONE running backfill, round-robin by oldest
  `updatedAt`.
- Per tick: list up to `batch_size` files for the cursor month from `pageToken`, filter,
  `convert` + `store.upsert`, persist state after every file. Page exhausted → previous month.
  No debounce (old files).
- `GdriveAuthError` → `status: error`, `error: "needs re-auth"`; `DriveRateLimited` → stop the
  tick, state unchanged; API-not-enabled → `error` with the enable-API message.
- Account removed → cancel; account disabled → skipped until re-enabled.
- Scheduler: `gdrive-backfill` every 120 s → `run_tick()`; idle ticks return
  `{"skipped": "idle"}` immediately.

### 8. API — `ghostbrain/api/routes/connectors.py`

Add `gdrive` to the connector list. Backfill routes under
`/v1/connectors/gdrive/accounts/{id}/backfill`:

| Method | Path | Body | Result |
|---|---|---|---|
| GET | `…/backfill` | — | state + progress, or 404 |
| GET | `…/backfill/estimate?years=N` | — | `{"files": int, "capped": bool, "since": "YYYY-MM-DD"}` |
| POST | `…/backfill` | `{"years": 1-10}` | 201 + state; 409 if the in-app scheduler is off |
| POST | `…/backfill/pause`, `…/backfill/resume` | — | state; 404 if none |
| DELETE | `…/backfill` | — | `{"ok": true}` |

Unknown account → 404; auth / API-not-enabled on estimate → 409 with the message.

### 9. UI

- `gdrive` appears in the connectors screen ("Google Drive"), connecting through the existing
  Google auth modal.
- `ConnectorAccounts` gets the backfill dialog + progress line for gdrive rows: years select
  (1/2/3/5, default 3), estimate line ("~N files · about H h at the current pace", pace =
  750 files/h; "5,000+" when capped), start; progress states running / paused / error
  (reauthorize + resume) / done (dismiss) with imported · updated · skipped · failed ·
  too large.
- Hooks and the dialog take a `connector` parameter (`useBackfill(connector, accountId)`, etc.)
  so they merge cleanly with the Gmail backfill's UI.

## Error handling

| Situation | Behaviour |
|---|---|
| Token missing / revoked | sync: account marked failed in `accounts_health`; backfill: `error` "needs re-auth", resume after reauthorize |
| Drive / Docs / Sheets API not enabled | clear "enable the X API" error in health check, run result and backfill state |
| One file fails to export/parse | counted `failed`, logged, next file |
| File > 200 MB | skipped as `too_large`, counted in run details / backfill state |
| Doc export > 10 MB | Docs API fallback |
| Empty extraction | note written with "No extractable text" body |
| Rate limited after 3 retries | run stops; sync keeps old `last_run`, backfill keeps cursor |
| Crash mid-page | resume from cursor + pageToken; `modifiedTime` check skips repeats |
| Note moved by the user | found by frontmatter id, updated where it lives |

## Testing

Fake Drive / Docs / Sheets services (`files().list/export/get_media`, `documents().get`,
`spreadsheets().get/values().batchGet`), test-first:

- **convert:** Doc markdown passthrough; >10 MB → Docs API converter (headings, lists, tables,
  links); Sheets multi-tab, row/col/tab caps with truncation lines, trimmed empties, pipe/newline
  escaping; XLSX fixture (formulas → values); PDF/DOCX via extractor; body cap; empty extraction;
  too-large skip without download.
- **filter:** owned vs modified-by-me vs shared-only.
- **store:** new → `process_event`; newer → in-place rewrite keeping context/frontmatter, no LLM;
  same → skip; stable filename; moved note found.
- **sync:** 7-day first window, debounce + `last_run` computation, rate-limit backoff + no
  `last_run` save, per-account auth failure.
- **backfill:** month stepping, pageToken paging, resume after crash, auth error → resume,
  API-not-enabled, cancel keeps notes, disabled/removed accounts, idle tick, capped estimate.
- **routes:** 201/404/409, estimate, pause/resume/cancel.
- **auth:** `_mod("gdrive")`, disconnect deletes token.
- **UI:** connector-parametrised hooks; dialog + estimate (incl. "5,000+"); progress states.
