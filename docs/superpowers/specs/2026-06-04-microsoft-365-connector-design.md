# Microsoft 365 Connector — Design

**Date:** 2026-06-04
**Status:** Approved (pending spec review)

## Summary

Add a Microsoft 365 connector family that ingests three Graph data sources into
Poltergeist's event queue: **Outlook mail**, **Teams chat messages**, and
**Teams meeting transcripts**. All three authenticate once via a shared
Microsoft Graph delegated (device-code) sign-in cached in the OS keychain.

This builds on a working prototype (`pull_transcript.py` + `setup.sh`) that
proved Graph delegated auth + keychain token caching + transcript fetch. The
prototype's auth and `resolve_meeting`/transcript logic carry over largely
intact; mail and chat are new.

The Microsoft tenant here is the **work tenant** (Entra app
`<entra-client-id>`, tenant
`<entra-tenant-id>`). This is distinct from the existing
Gmail connector, which targets the user's **personal Google** account.

## Architecture

A new connector family under `ghostbrain/connectors/microsoft/` with one shared
Graph auth core and three sibling connectors. Each sibling is a standard
`Connector` subclass (`ghostbrain/connectors/_base.py`) with its own routing
key, schedule cadence, and `.last_run` state — mirroring the existing
one-source-per-connector pattern (Gmail, Slack, Calendar, …).

```
ghostbrain/connectors/microsoft/
  __init__.py
  graph/
    __init__.py
    auth.py        # MSAL device-code flow + msal-extensions keychain cache
    auth_cli.py    # ghostbrain-microsoft-auth — one-time sign-in, shared by all three
    client.py      # thin Graph GET + @odata.nextLink paging helper; 401 → MicrosoftAuthError
  outlook_mail/
    __init__.py    # exports OutlookMailConnector
    connector.py
    runner.py      # run() -> RunResult via run_connector
    __main__.py    # CLI fetch entry
  teams_chat/
    __init__.py    # exports TeamsChatConnector
    connector.py
    runner.py
    __main__.py
  teams_meetings/
    __init__.py    # exports TeamsMeetingsConnector
    connector.py
    runner.py
    __main__.py
```

### Shared Graph auth (`graph/auth.py`, `graph/auth_cli.py`)

- A single `msal.PublicClientApplication` using the device-code flow, with an
  `msal-extensions` encrypted persistence token cache.
- Cache location: `~/.ghostbrain/state/microsoft/token_cache.bin` (aligns with
  the codebase state dir via `GHOSTBRAIN_STATE_DIR`, not the prototype's
  `~/.cache`). Falls back to a chmod-600 plaintext file with a warning if the
  OS vault is unavailable (carried over from the prototype).
- `CLIENT_ID` / `TENANT_ID`: the prototype values are baked in as defaults but
  are overridable from `routing.yaml:microsoft.client_id` /
  `microsoft.tenant_id`.
- Scopes requested = the **union** across all three connectors so one consent
  covers everything:
  `Mail.Read`, `Chat.Read`, `Calendars.Read`, `OnlineMeetings.Read`,
  `OnlineMeetingTranscript.Read.All`.
- `MicrosoftAuthError(RuntimeError)` mirrors `GmailAuthError`.
- `get_token()` reuses a cached account silently; if none, it raises
  `MicrosoftAuthError` instructing the user to run `ghostbrain-microsoft-auth`.
  (The interactive device-code flow runs only from `auth_cli.py`, never from a
  scheduled fetch.)
- `ghostbrain-microsoft-auth` runs the one-time device-code sign-in.

### Graph client helper (`graph/client.py`)

Small wrapper over `requests` holding a token: `get(path, params)` and
`get_all(path, params)` (follows `@odata.nextLink` paging). Raises on non-2xx;
maps 401 → `MicrosoftAuthError`. Keeps each connector's fetch logic free of HTTP
plumbing and makes them easy to unit-test with a mocked client.

## The three connectors

### `outlook_mail`
- **name:** `outlook_mail`
- **fetch(since):** query `/me/messages` for messages in monitored folders /
  categories OR unread within `unread_lookback_hours`, ordered by
  `receivedDateTime` desc, capped at a max-per-run. Apply the **denylist** then
  the **relevance gate** (see Noise gate below).
- **normalize → event:**
  - `id: microsoft:mail:<message id>`
  - `source: outlook_mail`, `type: email`
  - `title:` subject; `body:` text body (HTML stripped), capped
  - `actorId: microsoft:<sender address>`
  - `metadata:` from/to, folder, categories, isRead, conversationId, webLink,
    relevanceReason
- **Dedup:** `receivedDateTime > last_run`.

### `teams_chat`
- **name:** `teams_chat`
- **fetch(since):** list `/me/chats`; for chats with activity since `last_run`,
  pull `/me/chats/{id}/messages` created after `last_run` (capped per run via
  `max_messages_per_run`). Drop system/event messages. Apply the relevance gate.
- **normalize → event:**
  - `id: microsoft:chat:<chatId>:<messageId>`
  - `source: teams_chat`, `type: chat_message`
  - `title:` chat topic or participant summary; `body:` message text
  - `actorId: microsoft:<sender id/address>`
  - `metadata:` chatId, chatType (oneOnOne/group), participants, webUrl,
    relevanceReason
- **Dedup:** message `createdDateTime > last_run`.

### `teams_meetings`
- **name:** `teams_meetings`
- **fetch(since):** list `/me/events` over a rolling window
  (`calendar_lookback_days`, default 7) where the event has an online meeting.
  For each, resolve the `onlineMeeting` (reusing the prototype's
  `resolve_meeting`), list its transcripts, and emit **only transcripts with
  `createdDateTime > last_run`** — this is the dedup. Fetch each transcript's
  VTT text. **No relevance gate** (transcripts are deliberate).
- **normalize → event:**
  - `id: microsoft:transcript:<meetingId>:<transcriptId>`
  - `source: teams_meetings`, `type: meeting_transcript`
  - `title:` meeting subject; `body:` VTT transcript text, capped at
    `body_cap_chars` (default generous, e.g. 200_000)
  - `timestamp:` transcript end/created time
  - `metadata:` meetingId, transcriptId, organizer, attendees, joinWebUrl
- **Dedup:** transcript `createdDateTime > last_run`. The calendar window may
  look back further than `last_run` (transcripts lag the meeting), but only
  transcripts newer than `last_run` are emitted.

## Noise gate — shared helper

Extract the reusable core of the Gmail relevance gate (the `llm.run` call with a
JSON schema + USD budget, conservative keep-on-error) into a small
`ghostbrain/connectors/_relevance.py`. `outlook_mail` and `teams_chat` each use
it with their own prompt file (`90-meta/prompts/outlook-mail-relevance.md`,
`teams-chat-relevance.md`).

The existing **Gmail connector is not refactored** — the shared helper is only
introduced if it is clean to do so; otherwise mail/chat get a parallel gate
implementation. On LLM error the event is **kept** (noise removal never silently
swallows real signal). Relevance gate is on by default, disablable per connector
via `relevance_gate: false`.

## Data flow & dedup

Each connector uses the base `run()` loop: `fetch(since)` → `normalize(raw)` →
`_enqueue` JSON into `queue/pending/`, then `_save_last_run()`. The always-on
worker drains `pending/`. No new dedup state beyond the base `.last_run` file —
each source filters by its own timestamp field as described above.

## Integration

- **`ghostbrain/scheduler_jobs.py`** — import the three runners and register in
  `register_connectors`:
  - `outlook_mail` — `Interval(seconds=3600)` (every 1h)
  - `teams_chat` — `Interval(seconds=3600)` (every 1h)
  - `teams_meetings` — `Interval(seconds=7200)` (every 2h; transcripts lag)
- **`pyproject.toml`** — console scripts:
  - `ghostbrain-microsoft-auth = ghostbrain.connectors.microsoft.graph.auth_cli:main`
  - `ghostbrain-outlook-mail-fetch = ghostbrain.connectors.microsoft.outlook_mail.__main__:main`
  - `ghostbrain-teams-chat-fetch = ghostbrain.connectors.microsoft.teams_chat.__main__:main`
  - `ghostbrain-teams-meetings-fetch = ghostbrain.connectors.microsoft.teams_meetings.__main__:main`
  - Add dependencies: `msal`, `msal-extensions` (`requests` already present —
    verify during implementation).
- **`vault/90-meta/routing.yaml`** — a `microsoft:` block:
  ```yaml
  microsoft:
    client_id: "<entra-client-id>"   # optional override
    tenant_id: "<entra-tenant-id>"   # optional override
    outlook_mail:
      monitored_folders: []          # folder display names or well-known ids
      monitored_categories: []
      unread_lookback_hours: 24
      denylist_domains: []
      relevance_gate: true
      relevance_model: haiku
      max_messages_per_run: 50
    teams_chat:
      lookback_hours: 24
      max_messages_per_run: 100
      relevance_gate: true
      relevance_model: haiku
    teams_meetings:
      calendar_lookback_days: 7
      body_cap_chars: 200000
  ```
  Each runner returns `None` (skip, "not configured") when its sub-block is
  absent — matching the Gmail runner pattern.
- **Bootstrap prompts** — `ghostbrain/bootstrap.py` writes the new prompt files
  to `vault/90-meta/prompts/` (alongside `gmail-relevance.md`).

## Error handling

- Every run is wrapped by `run_connector` → `RunResult`; exceptions never leak to
  the scheduler.
- 401 / expired-beyond-refresh → `MicrosoftAuthError`; `health_check()` returns
  False with a message instructing the user to re-run `ghostbrain-microsoft-auth`.
- Per-source / per-chat / per-meeting failures are logged and the batch
  continues (Gmail pattern — one bad meeting doesn't sink the run).
- Relevance gate failures are conservative (keep the event).

## Testing

- **Connectors:** mock the Graph `client` and feed canned Graph payloads. Assert:
  - each `normalize` produces the documented event shape,
  - `last_run` dedup (mail/chat/transcript timestamp filtering),
  - relevance gate keep/drop and denylist behaviour (with a fake gate),
  - transcript window selection (calendar lookback vs `last_run` emit filter),
  - `health_check` False when no token / `MicrosoftAuthError`.
- **Auth:** token cache path resolution, `MicrosoftAuthError` raised when no
  cached account, scope union correctness. The interactive device-code flow
  itself is not unit-tested.
- Follow the existing `tests/` layout and the Gmail connector's mocking style.

## Prerequisite (outside the code — user / tenant admin)

The prototype's Entra app only has `OnlineMeetings.Read` +
`OnlineMeetingTranscript.Read.All`. Before mail/chat work, the app registration
needs, as **delegated** permissions, `Mail.Read`, `Chat.Read`,
`Calendars.Read` added, "Allow public client flows" enabled, and **admin
consent** re-granted on the work tenant.

## Out of scope (YAGNI)

- App-only / application permissions (delegated only).
- Sending mail / posting chat (read-only).
- Teams channel messages (only 1:1 + group chats via `/me/chats`); can be a
  later slice.
- An explicit chat allowlist (ingest all active chats, let the relevance gate
  filter); allowlist can be added later if noise warrants.
- Delta queries / webhooks (poll on `last_run`, consistent with other
  connectors).
