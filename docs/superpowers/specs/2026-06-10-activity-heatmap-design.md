# Activity Heatmap — Design

**Date:** 2026-06-10
**Status:** Approved (brainstormed with Jannik; visual companion session)
**Branch:** `feat/activity-heatmap` off `main` (independent of the jots/rich-editor PRs)

## Goal

A GitHub-style contribution heatmap of Poltergeist activity (captures, routings, digests, meetings, jots) per day: a compact tile on the dashboard and a dedicated screen with a full year and per-day drill-down.

Decisions made during brainstorming (visual companion):

1. **Placement (option B):** a 12-week mini-heatmap tile on the **today** dashboard + a dedicated **activity** sidebar screen with the full year, source filters, and a complete per-day log.
2. **Aggregation server-side:** new heatmap endpoint walks the audit files; the renderer never receives raw event streams for the year view.
3. What counts as activity: **every audit event** (no curation); the drill-down breaks counts down by source/verb so noise is inspectable rather than hidden.

## Data source

Audit logs at `vault/90-meta/audit/YYYY-MM-DD.jsonl` (one JSON event per line; the date is in the filename). History exists only from Poltergeist's first run — older days render as zero-level squares and that is acceptable.

## Backend

### 1. `GET /v1/activity/heatmap?days=365`

- `days`: 1–730, default 365.
- Walks the audit directory once; for each file in range, counts events and aggregates a per-source breakdown (`source` field when present, else event_type bucketed as `system`).
- Response:

```json
{
  "days": [
    { "date": "2026-06-04", "count": 23, "bySource": { "gmail": 9, "slack": 5, "system": 9 } }
  ],
  "total": 1204,
  "maxCount": 41
}
```

- Days with no audit file are omitted (the renderer fills zeros); `maxCount` lets the renderer bucket intensities without a second pass.
- Malformed lines are skipped with a `log.warning` (consistent with house style); a malformed file never 500s the endpoint.
- No caching: the files are small and append-only; React Query `staleTime` (60s) is the cache.

### 2. `GET /v1/activity?date=YYYY-MM-DD` (extend the existing endpoint)

- New optional `date` param, mutually exclusive with `windowMinutes` (if both given, `date` wins).
- Returns the existing `ActivityRow` shape (id, source, verb, subject, at, atRelative, path) for that single day, newest first, reusing the existing verb mapping and subject extraction in `ghostbrain/api/repo/activity.py`.
- Invalid date → 422.

## Desktop

### 3. `ActivityHeatmap` component (`desktop/src/renderer/components/ActivityHeatmap.tsx`)

- Props: `{ days, weeks, maxCount, onSelectDay?, selectedDate?, compact? }` where `days` is the heatmap payload mapped by date.
- CSS-grid, 7 rows × N week-columns, square cells, 5 intensity buckets (0 + quartiles of `maxCount`), neon-tinted scale consistent with design tokens (`--neon` at 25/50/75/100% alpha; level-0 uses the hairline tone).
- Accessible: each cell is a `button` with an aria-label like "2026-06-04 — 23 events"; keyboard focusable.
- Month labels along the top, weekday hints (mon/wed/fri) on the left in non-compact mode.

### 4. Today screen tile

- A compact 12-week `ActivityHeatmap` card in the dashboard grid; header "ghost activity"; clicking anywhere (or any cell) navigates to the activity screen (cell click preselects that day).

### 5. Activity screen (`desktop/src/renderer/screens/activity.tsx`)

- New `'activity'` entry in `ScreenId` + sidebar row (icon: `calendar-days` or closest Lucide equivalent, after `today`).
- Full-year `ActivityHeatmap` (52–53 weeks) at top; under it, the day log for the selected day (default: today): the `ActivityRow` list reusing the existing activity-feed row rendering, each row linking into `NoteView` when `path` is present.
- Source filter chips above the log (derived from the selected day's `bySource`; clicking filters the visible rows client-side).
- Hooks: `useActivityHeatmap(days)` and `useActivityForDate(date)` in `lib/api/hooks.ts`, both plain `useQuery` with 60s staleTime.

## Error handling

- Heatmap/day-log fetch failures render the standard panel error state (house pattern), never a blank card.
- Empty history: zero-level squares; the screen shows "activity appears as poltergeist lives with you" as the empty-day message.

## Testing

- Backend: aggregation unit tests against fixture audit files (multiple days, malformed line skipped, per-source counts, `maxCount`, `days` range bounds, omitted empty days); route tests for `?date=` (happy, invalid date 422, mutual exclusivity).
- Renderer: heatmap bucket assignment (0/levels by quartile), cell aria-labels, `onSelectDay` firing; screen test (heatmap renders from mocked payload, clicking a day loads that day's log, source chip filters rows); today-tile navigation test.

## Out of scope

- Streaks/longest-run statistics, weekly/monthly rollup charts.
- Backfilling activity for dates before audit logging existed.
- Importing GitHub-contribution data — the resemblance is visual only.
