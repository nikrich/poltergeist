# Connector Onboarding — Design

**Date:** 2026-07-07
**Status:** Approved for planning
**Scope:** In-app onboarding so a brand-new user can connect all 13 connectors through the UI — real OAuth/token/permission flows, a first-run wizard, and working connect/reauthorize/disconnect buttons. Retires the copy-paste recipe screen.

---

## 1. Problem

Today a new user faces the worst onboarding surface in the app:

- **`setup.tsx`** shows per-connector cards whose "setup" is a list of shell commands to copy-paste into a terminal (`ghostbrain-gmail-auth you@gmail.com`, `launchctl load ...`, hand-edit `routing.yaml`).
- The **connectors screen** (`connectors.tsx`) has real-looking **connect / reauthorize / pause / disconnect** buttons, but every one calls `stub(3)` — a "coming soon" toast. Only *sync now* / *sync all* work.
- Connector **status is inferred** from the presence of a `~/.ghostbrain/state/<id>.last_run` file or inbox captures. There is no `err` state, no "credentials present but never synced" state, and no account label.
- Nothing gates first launch — the app opens on the default screen even with an empty vault and zero connectors, giving no signpost toward "connect your sources."

The goal: a new user opens Poltergeist and is walked, in-app, from empty vault to connected sources, with each connector's real auth performed through the UI.

## 2. Goals / Non-goals

**Goals**
- Real in-app auth for all 13 connectors, reusing the existing Python auth code paths (no reimplementation in TypeScript).
- A first-run, full-screen, skippable wizard: welcome → vault → pick sources → connect each → done.
- Working `connect`, `reauthorize`, and `disconnect` on the connectors screen, sharing the same components the wizard uses.
- Honest connector status: distinguish `off` (no creds) / `on` (creds present, working) / `err` (creds present but auth/probe failing), with an account label where known.
- Guided BYO-credentials: for connectors that need a user-registered OAuth app (Google, Slack), the wizard walks the user through creating it with deep links and in-app paste/file-drop — no terminal.

**Non-goals**
- Bundling Poltergeist-owned OAuth apps / passing Google verification (explicitly deferred; BYO chosen).
- Multi-account management UI beyond "add another account" (v1 supports multiple accounts per connector via repeated connect, but rich per-account editing stays minimal).
- Replacing the scheduler or launchd model. Onboarding writes config + credentials; the existing scheduler picks them up.
- Rich routing.yaml editing (context mapping) beyond the minimum each connector needs to function. Advanced routing stays a manual/`routing.yaml` concern for now, surfaced as an optional step.

## 3. Connector inventory & auth taxonomy

The 13 connectors fall into six interaction patterns. The onboarding UI implements one reusable **flow component** per pattern; each connector declares which pattern it uses plus its parameters.

| # | Connectors | Pattern | Interaction |
|---|-----------|---------|-------------|
| A | `gmail`, `calendar` (Google) | **Browser OAuth (localhost redirect)** | User supplies a Google Desktop OAuth client (file-drop JSON, one-time), then per-account: app opens system browser → Google consent → `run_local_server` catches redirect → token saved. |
| B | `outlook_mail`, `teams_chat`, `teams_meetings` | **Device code** | Wizard shows the `login.microsoftonline.com/...` URL + user code; user signs in on any device; sidecar polls MSAL until the token is cached in keychain. One sign-in covers all three (union of scopes). |
| C | `slack`, `joplin` | **Paste token** | Guided steps (deep links to create the Slack app / open Joplin Web Clipper) + a paste field. Sidecar validates the token (`auth.test` for Slack, `/ping` for Joplin) before saving. |
| D | `github` | **External CLI login** | Detect `gh` presence + `gh auth status`. If logged out, show `gh auth login` guidance (device flow runs in `gh` itself). Probe verifies. No token stored by us. |
| E | `jira`, `confluence` | **API token (Atlassian)** | User creates an Atlassian API token (deep link), enters email + token + site. Sidecar validates via a `/myself` call, writes to `.env` + `routing.yaml`. Shared identity across both. |
| F | `calendar` (macOS), `claude_code`, `whisper` recorder | **Local permission / one-click enable** | No secret. macOS Calendar → trigger the EventKit permission prompt & confirm grant. Claude Code → write the `SessionEnd` hook into `~/.claude/settings.json` (with confirmation) and map project paths. Whisper → check ffmpeg/BlackHole/model presence, offer install guidance, enable in config. |

Notes:
- **Google** connectors share one OAuth client JSON and are presented together ("Google account" grants Gmail + Calendar in one consent when scopes are requested together; if only one is chosen, only that scope set is requested).
- **Microsoft** trio share one device-code sign-in; the wizard presents "Microsoft account" once and lets the user toggle which of mail/chat/meetings to enable.
- **Atlassian** (Jira + Confluence) share one email+token identity per site.
- So although there are 13 connectors, the wizard presents ~9 *connect cards*: Google (Gmail+Calendar), Microsoft (mail/chat/meetings), Slack, GitHub, Jira, Confluence, Joplin, macOS Calendar, Claude Code, Whisper recorder. (Jira/Confluence may share one card with two toggles; final grouping is a UI detail.)

## 4. Architecture

### 4.1 Overview

```
Renderer (wizard + connectors screen, React)
   │  start / poll status / submit input / disconnect   (React Query hooks)
   ▼
Electron main (api-forwarder.ts)  ──►  shell.openExternal(authUrl)   (system browser)
   │  localhost HTTP + Bearer token
   ▼
Python sidecar
   ├─ routes/connector_auth.py        (new FastAPI router)
   ├─ auth/session.py                 (new AuthSession manager, in-memory)
   ├─ auth/providers/*.py             (thin adapters over existing auth code)
   └─ repo/connectors.py             (extended: real state detection + creds probe)
        ├─ google InstalledAppFlow.run_local_server   (existing)
        ├─ msal device-code flow + keychain cache      (existing)
        ├─ slack/atlassian/joplin token validate+save  (existing + new validate)
        ├─ gh auth status probe                          (existing behavior)
        └─ writes routing.yaml + ~/.ghostbrain/state + .env
```

Rationale (chosen over Electron-native OAuth and CLI-spawning): all auth logic already lives in Python and is shared with the CLI entry points. The sidecar approach reuses it verbatim, keeps desktop thin, and keeps the CLI and desktop auth paths from diverging. Electron only opens the system browser and polls.

### 4.2 Auth-session API (new `routes/connector_auth.py`)

An **auth session** models one in-progress connect attempt. It is stateful (a browser flow or device-code poll takes seconds-to-minutes) so we model it as a short-lived server-side object keyed by a random `session_id`, held in `app.state` in memory. Sessions expire after a timeout (e.g. 5 min) and are cleared on completion.

Endpoints (all under `/v1/connectors/{id}`):

- `POST /auth/start` → begins a flow. Body carries pattern-specific params (e.g. `{ "account": "you@gmail.com" }` for Google, `{ "connectors": ["outlook_mail","teams_chat"] }` for Microsoft). Returns `{ session_id, status, next }` where `next` describes what the UI must do:
  - `open_browser` + `auth_url` (Google): main process calls `shell.openExternal`, then polls.
  - `show_device_code` + `verification_uri` + `user_code` (Microsoft): UI displays them, then polls.
  - `need_input` + `fields` (Slack/Joplin/Atlassian/Google-client-file): UI renders a form, then `submit`.
  - `need_grant` (macOS Calendar): sidecar triggers the OS prompt, UI polls.
  - `done` (GitHub already logged in; nothing to do).
- `GET /auth/status?session_id=…` → `{ status: "pending"|"waiting_input"|"success"|"error", detail?, account? }`. Polled by the UI.
- `POST /auth/submit` → supplies `need_input` fields (token paste, client-JSON contents, email/site). Validates; advances or errors.
- `POST /auth/cancel` → aborts a session (closes the localhost listener, stops device-poll).
- `DELETE /credentials` → disconnect: removes token files / keychain entry / `.env` lines / `routing.yaml` account block for that connector (+ account param where multi-account).

The three long-running flows (Google localhost listener, MSAL device poll) run in a background task/thread owned by the session; `GET /auth/status` reads its result. Google's `run_local_server` blocks, so it runs in a worker thread with the redirect listener; cancellation closes the socket.

### 4.3 Real status detection (`repo/connectors.py`)

Replace inferred on/off with a per-connector `probe()` returning `state` + `account` + `error`:

- **off** — no credential present (no token file / keychain entry / `.env` var / gh logout / hook absent).
- **on** — credential present *and* a lightweight liveness signal is OK (last_run recent, or a cheap validate succeeded, or captures exist). We keep last_run/inbox as the "has synced" signal but add a **credential-present** check so a freshly-connected-but-not-yet-synced connector reads as `on`/`connected (pending first sync)` rather than `off`.
- **err** — credential present but a validate/probe fails (revoked token, expired Atlassian token, `gh` logged out after being logged in, Google refresh failure). Populates `error` with a human string and drives the `reauthorize` button.

Probes must be cheap and offline-tolerant: prefer "credential file exists + not obviously expired" over always hitting the network. A deeper network validate runs on explicit "test connection" and right after connecting, not on every list call. `GET /v1/connectors` stays fast; expensive validation is opt-in.

### 4.4 Desktop wiring

- `api-forwarder.ts` already forwards arbitrary paths with the bearer token — the new routes need no forwarder changes except allowing them (they're GET/POST/DELETE, already permitted).
- New IPC/preload nicety: the renderer can't call `shell.openExternal` directly; add a `window.gb.shell.openExternal(url)` bridge (there's already `window.gb.shell.openPath`). The `open_browser` step calls it.
- New renderer API hooks in `lib/api/hooks.ts`: `useStartAuth`, `useAuthStatus` (polling), `useSubmitAuth`, `useCancelAuth`, `useDisconnectConnector`.

## 5. UX

### 5.1 First-run wizard

Full-screen, skippable, own route (`onboarding`), shown when a first-run flag is unset (persisted in desktop settings, not the vault). Steps:

1. **Welcome** — one screen: what Poltergeist does, "let's connect your sources."
2. **Vault** — confirm/choose the vault path (reuses existing vault-path logic + bootstrap). Runs `ghostbrain-bootstrap` equivalent if the vault tree is missing.
3. **Pick your sources** — grid of the ~9 connect cards with checkboxes; the user selects which to set up now. "You can add more later." Grouped: Google, Microsoft, Slack, Atlassian (Jira/Confluence), GitHub, Joplin, macOS Calendar, Claude Code, Whisper.
4. **Connect each** — steps through only the selected cards, one at a time, each rendering its pattern's flow component (§5.2). Progress rail on the side. Each card ends `connected` / `skipped` / `error`.
5. **Done** — summary of what's connected, "start syncing" (enables the scheduler if off) → lands on the connectors screen.

Skippable at any point via "I'll do this later" → sets first-run flag, lands on connectors screen. The connectors screen keeps an "add connector" entry that re-enters the same per-connector flow components (not the whole wizard).

### 5.2 Flow components (shared wizard ↔ connectors screen)

One component per pattern in §3, each driven by the auth-session API. Rendered inside a modal/panel on the connectors screen and inline in the wizard step:

- **GoogleAuthFlow** — first time: "drop your OAuth client JSON here" (file-drop → `submit`, one-time, reused for all Google accounts). Then per account: "Sign in with Google" button → `openExternal` → spinner polling status → success shows the account email. Advanced disclosure explains creating the GCP client with a deep link to the console + the exact APIs/scopes to enable.
- **DeviceCodeFlow (Microsoft)** — toggles for mail/chat/meetings → "Sign in" → shows `user_code` + a "copy & open" button to the verification URL → polls → success. Re-run just re-enables toggles.
- **TokenPasteFlow (Slack/Joplin)** — numbered guided steps with deep links (create Slack app / open Joplin Web Clipper), the required scopes listed, then a paste field. Submit validates before saving; inline error if the token is rejected.
- **AtlassianTokenFlow (Jira/Confluence)** — deep link to create the API token, fields for email + token + site URL, optional space keys for Confluence. Validates via `/myself`. Shared identity note ("this also connects the other Atlassian app").
- **CliLoginFlow (GitHub)** — detects `gh`. If missing: install link. If logged out: shows `gh auth login` with a "re-check" button (the device flow happens in `gh`; we can't drive it, but we detect completion). If logged in: instant `connected` + account login shown.
- **LocalGrantFlow (macOS Calendar / Claude Code / Whisper)** — macOS Calendar: "Grant access" triggers the OS prompt, re-check confirms. Claude Code: "Enable hook" writes the `SessionEnd` entry (shows a diff/confirmation first since it edits `~/.claude/settings.json`), plus a project-path → context mini-form. Whisper: dependency checklist (ffmpeg / BlackHole / model) with install guidance and an "enable recorder" toggle.

### 5.3 Connectors screen changes

- `connect {name}` (state `off`) → opens that connector's flow component. No more `stub(3)`.
- `reauthorize` (state `err`) → same flow, pre-filled where possible.
- `disconnect` → confirm → `DELETE /credentials` → connector flips to `off`.
- `pause` and the filter toggles: out of scope here (leave as-is / separate work), unless trivial. Flag in plan.
- The old `setup.tsx` recipe screen and `setup-content.ts` are **removed**; the "add connector" button opens a connector picker that reuses the wizard's card grid + flow components rather than navigating to `setup`.

## 6. Error handling

- Every flow surfaces a clear inline error state with a retry, distinct from "pending." Token validations return the provider's rejection reason where safe.
- Auth sessions time out server-side; the UI shows "timed out — try again" rather than spinning forever.
- Cancellation is explicit and cleans up (closes localhost listener, stops device poll) so a re-attempt doesn't collide on the redirect port.
- Writing `.env` / `routing.yaml` / `~/.claude/settings.json` is atomic (temp-file + `os.replace`, matching the existing recorder-settings writer) and merge-only so existing config/comments-lost-but-values-preserved semantics hold. Editing `~/.claude/settings.json` always shows the change for confirmation first.
- Secrets never transit through logs or the renderer state beyond the single submit; the renderer holds a token only long enough to POST it. Credentials continue to live in `~/.ghostbrain/state` (0600) / keychain / `.env`, never in renderer storage.
- Disconnect is best-effort and idempotent: missing files are not errors.

## 7. Testing

- **Python unit** — each provider adapter: start → status transitions → submit(valid/invalid) → success/err; disconnect removes the right artifacts; probe classifies off/on/err from fixture credential states. Network validates mocked.
- **Python API** — the auth-session routes with a fake provider: session lifecycle, expiry, cancel, 404 on unknown connector, bad-input 422.
- **Renderer** — each flow component with a mocked API: renders the right `next` step, polls, shows success/error, disconnect confirm. Wizard step machine: pick → connect selected only → skip → done. Follow existing Vitest + RTL patterns in `desktop/src/renderer/__tests__/`.
- **Status detection** — `repo/connectors.py` probe table against fixture states (token present/absent/expired) for representative connectors of each pattern.
- Manual verification per pattern against a real account for at least Google, Microsoft, Slack, Atlassian, GitHub before shipping (the auth dances can't be fully unit-tested).

## 8. Build sequence (for the plan)

1. Backend: `AuthSession` manager + `routes/connector_auth.py` with a fake provider; real `repo/connectors.py` state detection.
2. Provider adapters over existing auth code, one pattern at a time (start with paste-token — simplest — then Atlassian, GitHub probe, device-code, Google browser, local-grant).
3. `DELETE /credentials` disconnect per connector.
4. Preload `shell.openExternal` bridge + renderer API hooks.
5. Flow components (one per pattern) with tests.
6. Connectors-screen wiring (connect/reauthorize/disconnect real).
7. First-run wizard + first-run flag + route.
8. Remove `setup.tsx` / `setup-content.ts`; repoint "add connector."
9. End-to-end manual pass per pattern.

## 9. Open questions / deferred

- Google unverified-app warning: BYO client sidesteps our verification burden but the user still sees Google's "unverified app" screen for Gmail scopes on their own client — the Google flow's advanced copy must set that expectation. (Bundled apps were explicitly deferred.)
- macOS Calendar permission can't be programmatically confirmed beyond attempting an EventKit read; "grant" is best-effort with a re-check.
- Multi-account editing richness is intentionally minimal in v1.
