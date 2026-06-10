# Atlassian Import (Confluence + Jira picker) — Design

**Date:** 2026-06-10
**Status:** Approved (brainstormed with Jannik; visual companion session)
**Branch:** `feat/atlassian-import`, stacked on `feat/activity-heatmap` (or rebased to `main` after that merges)

## Goal

An in-app browser/picker to import specific Confluence pages and Jira issues into the vault on demand — complementing (not replacing) the connectors' scheduled time-window syncs.

Decisions made during brainstorming (visual companion):

1. **Flow (option B):** in-app browse + multi-select + bulk import. (Paste-a-URL and backfill flows were considered and rejected/deferred.)
2. **Confluence scope:** monitored spaces only (from `routing.yaml`'s `confluence.spaces`), expandable page lists, plus a title-search box across those spaces.
3. **Jira scope:** the connector's "my issues" JQL (assignee/reporter/watcher, recently updated) as the default list, plus a text-search box (JQL `text ~` under the hood).
4. **Pipeline reuse:** imported items run through the connectors' existing normalize → markdown → frontmatter → route pipeline, so imported notes are byte-compatible with synced ones and **re-importing updates the same note** (stable pageId/issue-key naming).

## Backend — `/v1/import` route family

New `ghostbrain/api/routes/import_atlassian.py` + repo module `ghostbrain/api/repo/import_atlassian.py`, wrapping the existing `AtlassianClient` (`ghostbrain/connectors/atlassian/_base.py`) and the confluence/jira connector conversion code (refactored into callable functions where currently embedded in the sync loop — the sync behaviour must not change).

### Browse endpoints (read-only)

| Endpoint | Returns |
|---|---|
| `GET /v1/import/confluence/spaces` | monitored spaces from routing.yaml: `[{site, siteSlug, key, name, context}]` |
| `GET /v1/import/confluence/pages?site=&space=&parent=?&limit=&cursor=?` | paged page list: `[{id, title, parentId, hasChildren, updatedAt, version}]` — top-level when no `parent` |
| `GET /v1/import/confluence/search?q=&limit=` | CQL `title ~ q` across monitored spaces: same page shape + `space` |
| `GET /v1/import/jira/issues?q=?&limit=` | no `q`: the connector's my-issues JQL, newest first; with `q`: `text ~ q` within configured sites. `[{site, key, summary, status, project, updatedAt}]` |

- All proxy through `AtlassianClient` (existing auth: `ATLASSIAN_EMAIL` + `ATLASSIAN_TOKEN[_<SLUG>]`, existing 429/5xx handling).
- Missing/invalid auth or no configured sites → `409 {"detail": "confluence connector not configured — run onboarding"}` (not a 500). Browse endpoints never write.

### Import endpoint

```
POST /v1/import   { "items": [
  { "kind": "confluence_page", "site": "...", "id": "12345" },
  { "kind": "jira_issue", "site": "...", "key": "PAS-1234" }
] }
```

- Max 50 items per request (422 above).
- Processes sequentially; each item: fetch full content → connector conversion (HTML→markdown for pages, ADF→text for issues, same truncation rules) → persist with the connector's deterministic naming → route through the existing router (one LLM call per item, accepted; the UI shows progress).
- Returns per-item results; a failed item never aborts the batch:

```json
{ "results": [
  { "kind": "confluence_page", "id": "12345", "ok": true, "path": "20-contexts/sanlam/confluence/....md", "context": "sanlam", "updated": false },
  { "kind": "jira_issue", "key": "PAS-9999", "ok": false, "error": "not found" }
] }
```

- `updated: true` when the item already existed in the vault and was overwritten (dedup by pageId/key).
- Audit: one `import_completed` event per item (source, id/key, ok, context) so imports appear in the activity feed/heatmap.

## Desktop

### Import screen

- New `'import'` in `ScreenId` + sidebar entry (icon `download`, after `connectors`).
- Two tabs: **confluence** and **jira** (house tab pattern). Each tab: search input at top, list below with checkboxes; confluence list starts at monitored spaces → expand a space to its top-level pages → expand pages with children. Jira tab lists my-issues by default; search replaces the list.
- A selection bar appears when ≥1 item is ticked: "import N selected" `Btn` (primary). During import: per-item progress (`3/7 — importing PAS-1234…`), then a summary toast (`imported 6 · 1 failed`) and inline per-item result marks. Failed items stay ticked for retry.
- Connector-not-configured (409) renders a call-to-action state linking to the connectors screen, not an error toast.
- Hooks: `useImportSpaces`, `useConfluencePages(space, parent?)`, `useConfluenceSearch(q)`, `useJiraIssues(q?)`, `useImportItems` (mutation; invalidates captures + activity queries on success).

## Error handling

- Per-item failures isolated (response shape above); network/auth failures on browse → standard panel error with retry.
- The import mutation never throws across IPC (existing ApiResult conventions).
- Routing falls back exactly like connector syncs (low confidence → inbox manual_review).

## Testing

- Backend: route tests with a mocked `AtlassianClient` (spaces from fixture routing.yaml; paged pages; search CQL; my-issues JQL; auth-missing → 409; POST import happy path writes the vault file with connector-identical frontmatter; re-import overwrites same path with `updated: true`; per-item failure isolation; >50 items → 422). A refactor-safety test pins that the scheduled connectors still produce identical output after the conversion code is extracted (golden-file comparison).
- Renderer: tab/search/checkbox flows with mocked API; selection bar count; per-item progress and failure marks; 409 call-to-action state.

## Out of scope

- Browsing ALL visible spaces / project-browse / raw JQL box (scoping decisions above).
- Paste-a-URL quick import and sync backfill buttons (deferred — flagged as good follow-ups).
- Importing attachments/images; Confluence page *trees* in one click (import is per-selected-item only).
- Non-Atlassian import sources.
