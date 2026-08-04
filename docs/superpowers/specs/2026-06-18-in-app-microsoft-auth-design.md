# In-App Microsoft Sign-In — Design

**Date:** 2026-06-18
**Status:** Approved (design); pending spec review
**Related:** [2026-06-04-microsoft-365-connector-design.md](./2026-06-04-microsoft-365-connector-design.md)

## Problem

Microsoft Graph auth is the only connector sign-in still done from a terminal:
the standalone `ghostbrain-microsoft-auth` CLI runs an MSAL **device-code** flow
(prints a code, the user pastes it into a browser). When the cached token lapses,
every Microsoft connector (`teams_meetings`, `teams_chat`, `outlook_mail`) silently
fails its health check and the scheduler skips it — with no in-app way to recover.
The user must know the CLI exists and run it by hand.

This was hit in practice: the token cache emptied, `teams_meetings` logged
`HealthCheckFailed`, and meeting transcripts stopped pulling in with no UI signal.

## Goal

Sign in to Microsoft from inside the Poltergeist desktop app with a **seamless,
no-code** experience: click **Connect Microsoft**, the system browser opens, you
sign in, and it completes on its own. One sign-in authorizes **all** Microsoft
connectors.

### Non-goals (deliberately scoped out)

- No token-refresh UI — MSAL silent refresh already handles renewal; the card only
  reflects failures.
- No per-connector enable/disable toggles — one Microsoft identity covers all three
  connectors.
- The headless `ghostbrain-microsoft-auth` CLI stays as a fallback (shares the same
  token cache); it is not removed.

## Approach

Surface MSAL's **interactive** flow (`acquire_token_interactive`) through the
existing local sidecar API and a Settings card. The interactive flow opens the
system browser and runs an ephemeral `localhost` loopback listener that captures the
redirect automatically — no device code to copy.

The flow runs **in the Python sidecar**, which already owns MSAL and the shared
encrypted token cache. Keeping all token handling in one place avoids splitting
OAuth state between the TypeScript main process and Python. The renderer never
touches OAuth — it triggers the flow and polls status.

Considered and rejected:
- **In-app device-code** (reuse current flow, surface code + button in UI). No Azure
  change needed, but still requires the user to copy a code — not "seamless".
- **Electron-native auth** (BrowserWindow in main process captures the redirect, then
  hands the token to Python). Duplicates token handling outside MSAL's cache and
  splits ownership across TS/Python. More moving parts for no UX gain.

## Architecture & data flow

```
Settings UI ──POST /v1/connectors/microsoft/auth/start──▶ sidecar
                                                          └─ background thread:
                                                             acquire_token_interactive
                                                               • opens system browser
                                                               • ephemeral localhost loopback
                                                               • user signs in → redirect captured
                                                               • token written to shared cache
Settings UI ──GET  /v1/connectors/microsoft/auth/status─▶ { state, account?, error? }   (poll ~1s)
Settings UI ──POST /v1/connectors/microsoft/auth/disconnect─▶ remove account + clear cache
```

`acquire_token_interactive` is blocking, so it runs off the event loop in a worker
thread. `start` returns immediately; the UI polls `status` until terminal. A
single-flight guard rejects overlapping sign-ins.

## Components

### 1. `ghostbrain/connectors/microsoft/graph/interactive_auth.py` (new)

Owns the interactive flow and its observable state, isolated from FastAPI.

- `AuthState` dataclass: `state: "idle" | "pending" | "connected" | "error"`,
  `account: str | None`, `error: str | None`.
- `InteractiveAuth` holder (one per app process):
  - `start(config) -> None` — single-flight; raises `AlreadyRunning` if a flow is in
    flight. Spawns a thread that calls the injected MSAL app's
    `acquire_token_interactive(resolve_scopes(config))`, then sets state to
    `connected` (with the signed-in username) or `error` (mapped message).
  - `status(config) -> AuthState` — if no flow in flight, derives the real state from
    `have_token(config)` (→ `connected`/`idle`) so the card is accurate on app load.
  - `disconnect(config) -> None` — `app.remove_account(...)` for each cached account
    and clears the cache file → `idle`.
- The MSAL `PublicClientApplication` is built via the existing `_build_app(config)`
  but **injectable** for tests (no real browser/network in unit tests).
- Error mapping (MSAL result/exception → human message): user cancelled/closed
  browser, consent denied, no browser available, loopback timeout (~3 min cap),
  loopback port in use.

### 2. `ghostbrain/api/routes/ms_auth.py` (new), wired in `api/main.py`

- `POST /v1/connectors/microsoft/auth/start` → `{state:"pending"}`, or `409` if a
  flow is already running.
- `GET  /v1/connectors/microsoft/auth/status` → `AuthState` as JSON.
- `POST /v1/connectors/microsoft/auth/disconnect` → `{state:"idle"}`.

The `InteractiveAuth` holder lives on `app.state` (process singleton). Routes read
the Microsoft config block from the same routing source the runners use.

### 3. Renderer — Microsoft connector card (Settings)

- `useMicrosoftAuth` hook: `connect()` (POST start, then poll status ~1s until
  terminal, with a client-side timeout), `disconnect()`, and current `status`.
- `MicrosoftConnectCard` (presentational): shows **Connected as `you@tenant`** /
  **Not connected** / inline **error message + Retry**; a **Connect Microsoft**
  button (spinner while `pending`) and **Disconnect** when connected.
- No Electron main-process change: the existing api-forwarder passes arbitrary paths
  through to the sidecar.

### 4. Config — `vault/90-meta/routing.yaml`

Remove the `microsoft.scopes` narrowing so it falls back to the `SCOPES` union
already defined in `auth.py`:
`Mail.Read, Chat.Read, Calendars.Read, OnlineMeetings.Read, OnlineMeetingTranscript.Read.All`.
This supersedes the interim `Calendars.Read` addition (the union covers it) and is
what lets one sign-in authorize all three connectors.

### 5. Azure app registration (one-time, manual)

Document in the implementation plan and README:
- *Authentication → Mobile and desktop applications* → add redirect URI
  **`http://localhost`**.
- *Authentication → Advanced settings* → **Allow public client flows: Yes**.

Without the loopback redirect URI, `acquire_token_interactive` cannot capture the
redirect and sign-in fails.

## Error handling

All failures surface as `status: "error"` with a human message; the card renders it
and offers **Retry**. The single-flight guard prevents overlapping flows (`409`).
Health checks for the three connectors are unchanged — once the cache is populated
they pass automatically on the next scheduled run.

## Testing (TDD)

- **Python unit (`interactive_auth`)**, MSAL app injected/mocked:
  `pending → connected` happy path and account extraction; each error → mapped
  message; single-flight guard (`AlreadyRunning`); `status` derives from
  `have_token` when idle; `disconnect` removes accounts and clears the cache. No real
  browser or network.
- **API (`TestClient`)**: `start`/`status`/`disconnect`, `409` on overlap, and
  `status` reflecting `have_token` when no flow is in flight.
- **Renderer (Vitest + mocked api-forwarder)**: Connect triggers start and polls to
  connected, renders the account; error path renders the message + Retry; Disconnect
  resets to "Not connected".

## Rollout / verification

1. Apply the Azure redirect-URI change.
2. Remove the `microsoft.scopes` narrowing in `routing.yaml`.
3. In Settings, click **Connect Microsoft**, sign in, confirm the card shows
   "Connected as …".
4. Trigger a `teams_meetings` sync from the connectors UI and confirm a transcript
   lands in the queue.
