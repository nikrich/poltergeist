# Meeting Prep — Design

**Status:** draft
**Date:** 2026-05-25
**Owner:** @nikrich

## Summary

A meeting-prep feature for Poltergeist that (1) fires a native macOS notification
15 minutes before each calendar meeting, and (2) shows a prep panel for any
upcoming meeting in the Meetings tab. The prep panel combines the raw calendar
event detail, related items found via the existing semantic index, and a short
LLM-generated brief produced by shelling out to `claude -p`.

## Goals

- Notify the user 15 minutes before a meeting starts, via a native notification
  that opens the prep view when clicked.
- Show prep content for the currently-relevant meetings without making the user
  search the vault.
- Pre-warm the brief for the next upcoming meeting so the notification-click
  experience is instant.
- Generate briefs lazily for other upcoming meetings the user clicks into.

## Non-goals

- Configurable lead time, multiple notifications, or settings UI for this
  feature. Lead time is hard-coded at 15 minutes; iterate later if needed.
- In-app banners, auto-window-focus, or any notification surface beyond the
  native macOS one.
- Editing prep notes by hand. The brief and related-items are derived; the
  underlying calendar event is the source of truth.
- Notifications for all-day events, declined meetings, or events without a
  start time. Out of scope for v1.

## User flow

### Notification path
1. Sidecar scheduler tick (every 60s) sees the next upcoming meeting is within
   T-20 min and pre-warms its brief in the background.
2. Electron main-process poll (every 60s) sees that meeting is within T-15 min
   and the event id is not in the persisted notified-set. Fires a native
   `Notification`. Records the id so it doesn't fire again on app restart.
3. User clicks the notification. Main process shows/focuses the window and
   sends `gb:meetings:openPrep(event_id)` over IPC.
4. Renderer navigates to the Meetings tab, scrolls to the matching row in the
   `UpcomingMeetings` list, expands it. `<MeetingPrep />` mounts and fetches
   `GET /v1/meetings/prep/{event_id}` — cache hits because of the pre-warm,
   so content renders instantly.

### Manual path
1. User opens the Meetings tab. The new `UpcomingMeetings` section sits
   between the existing `PreMeeting` hero and the `MeetingHistory` panel and
   lists today's remaining events as rows.
2. User clicks any row. Inline expansion mounts `<MeetingPrep />` for that
   event. If cached, renders instantly; otherwise the sidecar generates
   synchronously and the panel shows a brief loading state.

## Architecture

Work splits across the two processes that already exist:

- **Electron main process** owns notification timing. No LLM logic, no vault
  knowledge — just agenda polling and `Notification` firing. Mirrors the
  pattern in `desktop/src/main/tray.ts` where `notifyFailure` fires native
  notifications today.
- **Python sidecar** owns brief generation. The new `meeting_prep` module
  lives next to the vault and the semantic index. Exposed via HTTP so the
  desktop never imports vault logic.
- **Scheduler** in the sidecar pre-warms the next upcoming meeting's brief so
  the notification click is instant.

Cache lives on disk at `~/ghostbrain/cache/meeting-prep/<event_id>.json`. The
notified-set lives at `~/ghostbrain/cache/notified.json` (managed by the main
process).

## Components

### Backend (sidecar)

**`ghostbrain/worker/meeting_prep.py`** — new module. Pure builder:
```
build_prep(event_id: str) -> Prep
```
- Resolves the event id back to its calendar note path (uses the same vault
  glob the agenda repo uses).
- Reads the frontmatter: `title`, `start`, `end`, `with`, `location`,
  `description`.
- Queries the semantic index for related items. Two queries: one by title +
  attendee names, one by attendee email handles. De-dupes and keeps the top N
  (5–8) by score.
- Composes a prompt and shells out to `claude -p` (project-standard LLM path
  per memory `llm_backend.md`). Captures stdout; on non-zero exit or timeout,
  returns `brief=None` with an error string.
- Returns `{brief, related, event_snapshot, generated_at, error}`. The
  `event_snapshot` carries the hash of `start|end|description` used for cache
  invalidation.

**`ghostbrain/api/repo/meeting_prep.py`** — cache wrapper.
- `get_prep(event_id)` — read cache file; if hash matches the current event,
  return it; otherwise return `None`.
- `set_prep(event_id, prep)` — atomic write (temp file + rename).
- `prewarm(event_id)` — runs `build_prep` in a thread pool; returns
  immediately. Subsequent reads see the cache when it lands.

**`ghostbrain/api/routes/meetings.py`** — extend with:
- `GET /v1/meetings/prep/{event_id}` → cached `Prep` if present, otherwise
  generates synchronously and caches. Returns the same `Prep` shape either
  way.
- `POST /v1/meetings/prep/{event_id}/prewarm` → fire-and-forget. 202
  Accepted.

**`ghostbrain/scheduler_jobs.py`** — add `meeting_prep_prewarm` job, every
60s. Reads today's agenda; finds the first event with status `upcoming` whose
start is within `[now, now + 20min]`. If `get_prep` returns `None`, calls
`prewarm`.

### Frontend (Electron main)

**`desktop/src/main/meeting-notifier.ts`** — new file.
- Polls `GET /v1/agenda` every 60s.
- For each event with a parseable start time and status `upcoming`, computes
  `start - 15min`. If `now ≥ that` and event id is not in the persisted
  notified-set, fires:
  ```ts
  new Notification({
    title: `${event.title} in 15 min`,
    body: event.with.length ? `with ${event.with.slice(0, 3).join(", ")}` : "",
    silent: false,
  })
  ```
- Click handler shows/focuses the most recent window and sends
  `gb:meetings:openPrep(event_id)` via `webContents.send`.
- Notified-set persisted to `~/ghostbrain/cache/notified.json` after each
  fire. Pruned daily — drop ids whose start was more than 24h ago.

**`desktop/src/main/index.ts`** — wire up the notifier the same way the tray
gets installed today. One `installMeetingNotifier({ sidecarUrl })` call;
disposed alongside the tray.

### Frontend (renderer)

**`desktop/src/renderer/screens/meetings.tsx`** — add an `UpcomingMeetings`
component between the existing `PreMeeting`/`IdleLobby` hero and
`MeetingHistory`. Lists today's `upcoming` events as rows (skip the one
already shown in the hero card). Each row is collapsible; clicking expands a
`<MeetingPrep />` panel beneath the row.

**`desktop/src/renderer/components/MeetingPrep.tsx`** — new component.
Three sections in order:
1. **Event detail** — time range, attendees (reuse `AttendeeRow`), location,
   raw description from the invite. Compact.
2. **Brief** — single paragraph of LLM-generated context. Includes a small
   "regenerate" button that hits the prewarm endpoint and refetches.
3. **Related** — clickable links to vault notes from the semantic search.
   Each row shows title, source (calendar / email / slack / etc.), and a
   one-line snippet. Click → open in `NoteView`.

States: loading (spinner only), success (full panel), error (event detail +
related still render, brief slot shows an inline error + retry).

**`desktop/src/renderer/lib/api/hooks.ts`** — add `useMeetingPrep(eventId)`.
TanStack Query, `staleTime: Infinity`, `enabled: !!eventId`.

**`desktop/src/renderer/stores/meeting.ts`** (or a sibling store) — add a
small selected-event id slice so the IPC handler can request "open this
event" from outside the component tree.

**`desktop/src/renderer/App.tsx`** — IPC listener for `gb:meetings:openPrep`.
Navigates to the Meetings tab and writes the event id into the selected-event
slice. The `UpcomingMeetings` list reads that slice and auto-expands the
matching row.

## Data flow

```
sidecar scheduler  ──tick 60s──▶  pick next upcoming meeting
                                    │
                          within T-20m and not cached?
                                    │ yes
                                    ▼
                           build_prep(event_id)
                                    │
                                    ▼
                     ~/ghostbrain/cache/meeting-prep/<id>.json

electron main  ──poll 60s──▶  GET /v1/agenda
                                    │
                       any event past its T-15 and not yet notified?
                                    │ yes
                                    ▼
                          new Notification(...)
                                    │
                              user clicks
                                    ▼
                  show window + IPC gb:meetings:openPrep(id)

renderer  ──IPC──▶  navigate to /meetings + select event id
                                    │
                                    ▼
                       UpcomingMeetings row expands
                                    │
                                    ▼
                       useMeetingPrep(id) → GET /v1/meetings/prep/{id}
                                    │
                              cache hit (pre-warmed)
                                    ▼
                          MeetingPrep renders instantly
```

## API shapes

```ts
interface Prep {
  eventId: string;
  brief: string | null;
  related: RelatedItem[];
  eventSnapshot: {
    title: string;
    start: string;       // ISO
    end: string;         // ISO
    with: string[];
    location: string;
    description: string;
    hash: string;        // hash(start|end|description) for cache busting
  };
  generatedAt: string;   // ISO
  error: string | null;
}

interface RelatedItem {
  path: string;          // vault-relative
  title: string;
  source: string;        // "calendar" | "email" | "slack" | "jira" | …
  snippet: string;
  score: number;
}
```

## LLM prompt outline

Prompt fed to `claude -p`, kept short:

```
You are preparing a 1-paragraph brief (≤60 words) for an upcoming meeting.

Meeting:
- Title: {title}
- When: {start} → {end}
- Attendees: {attendees}
- Location: {location}
- Invite description: {description}

Related context from the vault (most relevant first):
{for each related item: "- [{source}] {title} — {snippet}"}

Write the brief in plain prose. Focus on what's likely on the table and any
unresolved threads from prior context. No filler, no bullet points, no
greetings. If there is no useful context, say so in one sentence.
```

## Error handling

- **`claude -p` fails or times out (30s).** `build_prep` returns
  `brief=None` with an error string. Cached anyway. UI renders event detail
  + related, with an inline error and a regenerate button in the brief slot.
- **Semantic index empty or new vault.** `related: []`. UI hides the Related
  section.
- **Calendar event deleted after caching.** Cache still serves on direct id
  lookup; agenda no longer lists it, so it stops showing in
  `UpcomingMeetings`. Click-from-notification still works as long as the
  cache file exists.
- **Event rescheduled.** Cache busts on `start|end|description` hash change
  the next time `get_prep` is called; next access regenerates.
- **Notification permission denied** (macOS user hasn't granted it).
  `Notification.isSupported()` is false or the constructor throws; main
  process logs and no-ops. In-app prep still works through the Meetings tab.
- **Sidecar down when notifier polls.** Fetch throws; notifier swallows and
  retries next tick. No notification fires, but no crash.
- **App restart after a meeting was already notified.** Persisted
  notified-set prevents duplicate fires.
- **Notification fires while the app window is closed.** `Notification`
  works regardless of window state (the app stays alive in tray). Click
  handler restores/shows the window.

## Testing

**Backend unit (`tests/test_meeting_prep.py`):**
- `build_prep` with a mocked `claude -p` subprocess and a fixture vault:
  cache write happens, snapshot hash includes start/end/description,
  regeneration triggers when the description changes.
- Timeout path returns `brief=None` and an error string.
- `prewarm` is fire-and-forget — caller returns quickly while the cache
  file lands asynchronously.

**Backend integration (`tests/test_route_meeting_prep.py`):**
- `GET /v1/meetings/prep/{event_id}` cache miss → generates and returns
  Prep.
- Cache hit returns immediately (no LLM call).
- Stale cache (snapshot hash mismatch) → regenerates.
- Unknown event id → 404.

**Scheduler:**
- Unit test for the "should prewarm" predicate: returns the right event id
  for a fixture agenda + clock.

**Renderer (`desktop/src/renderer/__tests__/MeetingPrep.test.tsx`):**
- Loading state shows spinner.
- Success renders all three sections.
- Brief-null with error shows the inline error + regenerate button.
- Empty related list hides that section.
- `useMeetingPrep` is disabled when `eventId` is null.

**Main process:**
- Extract `shouldFireNow(event, now, notifiedSet)` into a pure function.
  Unit-test boundary cases: exactly T-15, T-15 + 1ms, already-fired,
  unparseable start time, event already passed.
- The IPC click handler is exercised via a smoke test that injects a fake
  `BrowserWindow` and asserts `webContents.send` was called with the right
  channel + event id.

## Open questions

None as of this draft.

## Implementation order

1. Backend: `meeting_prep.py` + cache repo + `GET /v1/meetings/prep/{id}` +
   tests. Verifiable in isolation by hitting the endpoint.
2. Backend: scheduler prewarm job + tests.
3. Frontend renderer: `<MeetingPrep />` + `useMeetingPrep` + tests, wired to
   a temporary "test event" button so the panel can be exercised before the
   list and notifier exist.
4. Frontend renderer: `UpcomingMeetings` list + selected-event store + auto-
   expand behavior.
5. Frontend main: `meeting-notifier.ts` + IPC plumbing + notified-set
   persistence + click → focus + navigate. Smoke-test by setting a real
   calendar event 16 minutes in the future.
6. Polish: regenerate button, related-item rendering, error states.
