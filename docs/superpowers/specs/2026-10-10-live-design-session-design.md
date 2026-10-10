# Live design session — design spec

**Date:** 2026-10-10
**Status:** approved in conversation (user then asked for autonomous build; the
remaining calls below were made without further review and are marked *decided*).

## Goal

While a meeting is being recorded, the user can say "let's kick off a frontend
prototype" and Poltergeist starts building a **real, working React prototype**
in a side panel, styled with a chosen **design system**, and keeps revising it
as the conversation continues. Saying "let's focus on the backend now" moves
focus to an **event-storming board** (with a derived architecture diagram).
"Let's stop prototyping" pauses. The prototype can be popped out into its own
window for screen-sharing, and is saved into the project folder afterwards.

## What the user said (brief)

- Private side panel by default; pop-out window for screen-sharing (C).
- Design systems from **any** source (Claude Design, local folder, URL, Figma…).
- Design systems can be **attached per project**.
- Update trigger: design-relevance detection + manual "Update now" + typed nudges (D).
- Output: a real working React prototype for UI talk; event-storming
  architecture diagrams for backend talk. Both canvases in one meeting (A).
- Spoken commands start / switch / stop: natural phrasing with an undoable
  toast, no wake word.
- Stopping is a pause; it can be resumed in the same meeting.

## Architecture

Built-in feature (not a plugin): it needs the sidecar's live transcript, a
custom Electron protocol and an in-process bundler.

```
recorder/live.py ─ segments ─▶ ghostbrain/design/   (sidecar, new package)
                                 commands.py   spoken-command detection
                                 relevance.py  design-talk filter + canvas routing
                                 session.py    per-recording state machine + loop
                                 ui_agent.py   claude -p, cwd = prototype dir
                                 board_agent.py JSON event-storming model
                                 packs.py      design-system library + import
                                        │
                  SSE /v1/design/live  ·  REST /v1/design/*
                                        ▼
Electron main: design-bundler.ts (esbuild-wasm) + gbproto:// protocol
                                        ▼
Renderer: DesignPanel (Prototype | Board tabs) beside LiveTranscriptPanel
          Pop-out BrowserWindow (#/design-popout) for screen-share
```

### Sidecar: `ghostbrain/design/`

**Session registry.** One `DesignSession` per recording (keyed by wav path),
created lazily: the *design listener* starts with live transcription (when the
`design.listen` setting is on, default on) and follows `live.follow(wav)` on
its own thread. It costs nothing until a spoken command or a manual start
activates a canvas.

**Commands (`commands.py`).** Each new segment is appended to a rolling window
(last ~45 s). A cheap regex prefilter (prototype, frontend, front end, UI,
screen, mockup, wireframe, backend, back end, event storm, domain, design,
stop, park, pause, resume, pick … back up, switch, focus) gates a `fast`-tier
LLM call that returns
`{"command": "start_ui"|"start_board"|"focus_ui"|"focus_board"|"pause"|"resume"|"nudge"|"none", "canvas": "ui"|"board"|"both"|null, "text": str|null}`.
Segments already classified are never re-sent (cursor by seq). A command
emits a `command` event with an `undo_token`.

**Relevance (`relevance.py`).** While a canvas is active, new segments
accumulate in that canvas's buffer. A `fast`-tier call classifies the
buffered text as relevant to the focused canvas or not (`{"relevant": bool,
"summary": str}`); irrelevant text is dropped. An update fires when relevant
text ≥ 20 s of speech, or a 6 s pause follows relevant text, or on
force/nudge. *Decided:* text relevant to the *unfocused* canvas is ignored
(spoken focus wins, per the user's voice-command requirement).

**Loop (`session.py`).** Per canvas: state `off → active ⇄ paused → ended`;
at most one agent run in flight; input arriving mid-run waits for the next
run. Recording end → `ended` after one final run if the buffer is non-empty.
Every state change and run result is an SSE event and a `session.jsonl` line.

**UI agent (`ui_agent.py`).** `claude -p --output-format json` with
`cwd = <prototype dir>`, `--allowedTools Read,Write,Edit,Glob,Grep`,
`--permission-mode acceptEdits`, `balanced` tier, `--max-budget-usd` from
`design.budget_usd` (default 2.00 — the 0.50 default is too low for agentic
edits), `--resume <session_id>` after the first run so the agent keeps
context. Prompt: the system rules (React 18 + TypeScript, files under `src/`,
entry `src/App.tsx`, hash routing via the provided `router.tsx`, mock data in
`src/data.ts`, style only with the pack's tokens, never touch `design-pack/`),
the design pack's `README.md`/`components.md`, the new transcript excerpt, and
nudges. A build-error report from the desktop triggers a fix run (max 2 in a
row). Each successful run is a git commit in the prototype dir (`rev N`).
*Decided:* Claude provider only for the UI agent (needs file-edit tools);
if the active provider isn't `claude`, the canvas reports `unavailable` with
a reason. Command/relevance calls use the configured provider.

**Board agent (`board_agent.py`).** `balanced` tier, single JSON call given
the current `board.json` and the excerpt, returns the full updated model:

```json
{"contexts":[{"id","name"}],
 "items":[{"id","kind":"event|command|aggregate|policy|read_model|external|actor|hotspot",
           "label","context","order"}],
 "links":[{"from","to"}]}
```

Validated with a schema; ids stable; written atomically; committed as a rev.

**Design packs (`packs.py`).** Library at
`<vault>/90-meta/design-systems/<id>/` with `pack.json`
(`{id, name, source, imported_at}`), `tokens.css`, `README.md` (rules,
components), optional `assets/` and `reference/`. A built-in `poltergeist-neutral`
pack ships with the app so the feature works with no import.
**Import is agent-driven:** `claude -p` with cwd = a staging dir,
tools `Read,Write,Glob,Grep,WebFetch,DesignSync` plus the user's configured
MCP servers (Figma etc.), told to produce exactly the pack files from a
source string (Claude Design URL/name, folder path, URL, Figma link). The
result is validated (tokens.css non-empty, README present) and moved into
the library. Runs as a background job with status polling.

**Projects.** `Project` gets `design_system: str | None`. Starting a session
picks the project (from the recording's calendar title, else none) and its
pack (else the user's last pick, else neutral). Both can be changed in the
panel before the first run; changing the pack after copies the new pack in
and forces an update.

**On disk.** Prototype dir: with a project →
`20-contexts/<ctx>/projects/<slug>/prototypes/<YYYY-MM-DD>-<slug(title)>/`;
without → `20-contexts/<ctx>/prototypes/…`. Contents: `src/` (scaffold:
`main.tsx`, `App.tsx`, `router.tsx`, `data.ts`, `styles.css`),
`design-pack/` (copy), `board.json`, `session.jsonl`, `.git/`. On end, a
`README.md` index note links meeting + prototype; "Eject" writes
`package.json` + `vite.config.ts` + `index.html` so `npm i && npm run dev` works.

### REST + SSE (`/v1/design`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/live` | SSE: state, command (with undo token), run-started, revision, error, end |
| GET | `/session` | current session snapshot (or 404) |
| POST | `/session/start` | `{canvas}` manual start / focus |
| POST | `/session/pause` · `/resume` | `{canvas}` |
| POST | `/session/nudge` | `{canvas?, text}` — forces a run |
| POST | `/session/update` | `{canvas?}` — force run on buffer |
| POST | `/session/undo` | `{token}` |
| POST | `/session/config` | `{project_id?, pack_id?}` |
| POST | `/session/build-error` | `{rev, message}` from desktop |
| POST | `/session/revert` | `{canvas, rev}` |
| POST | `/session/eject` | writes Vite files, returns path |
| GET | `/packs` · POST `/packs/import` · GET `/packs/import/{job}` · DELETE `/packs/{id}` | library |

### Desktop

- **`design-bundler.ts`** (main): esbuild-wasm bundles `src/main.tsx` from a
  prototype dir into `dist/` inside it; `react`, `react-dom`, `react/jsx-runtime`
  resolve to the app's own copies through an `onResolve/onLoad` plugin that
  reads with `fs` (asar-safe); CSS imports inline. Returns `{ok, rev}` or the
  formatted errors (the renderer posts them to `/session/build-error`).
- **`gbproto://`** protocol: serves `dist/` + `design-pack/` of the current
  session's prototype dir only (path-checked like `gbdoc://`). Standard +
  secure scheme so `sessionStorage` works for state survival.
- **`DesignPanel`** (meetings screen, docked beside the live transcript while
  recording): header (project picker, pack chip, state pill), tabs
  Prototype | Board (focused tab marked), footer (nudge input, Update now,
  Pause/Resume, Pop out, rev ◀ ▶, Eject when ended). Command toasts with Undo.
- **Prototype frame:** a double-buffered iframe — the new bundle loads in a
  hidden iframe at the current hash and swaps in on `load`, then restores scroll
  via `postMessage`, so updates never flash.
- **Board view:** stickies laid out deterministically (columns by `order`,
  lanes by context, colours by kind) with SVG arrows; an "Architecture" toggle
  renders a mermaid flowchart derived from the model (contexts as subgraphs,
  commands → aggregates → events → policies).
- **Pop-out:** `BrowserWindow` loading the renderer at `#/design-popout`,
  showing only the focused canvas + a slim "updating…" bar.
- **Settings:** Design section — listen for spoken commands (on), budget per
  run, design-system library (list, import from source string, delete),
  per-project design system (projects settings).

## Error handling

- Nothing in the design session may affect recording or live transcription:
  the listener catches everything and degrades to `state: unavailable` + reason.
- LLM failure on a run → `error` event, canvas stays `active`, next trigger
  retries. Three consecutive failures → `paused` with reason.
- Build error → fix run (max 2); the frame keeps the last good bundle.
- Sidecar restart mid-meeting → session rebuilt from `session.jsonl`
  (canvas states, revs, CLI session ids) on the next `/live` subscription.
- Import failure → job `error` with the agent's last message; nothing written
  to the library.

## Testing

- Python (pytest, fake LLM via the provider seam / `client.run` patch, fake
  live follower): command parsing + prefilter, relevance buffering and
  trigger thresholds, state machine (start/focus/pause/resume/undo/end),
  single-flight runs, fix-run cap, board validation + atomic write, pack
  library + import validation, routes (snapshot, SSE events, 404s),
  project `design_system` round-trip, scaffold + eject.
- Desktop (vitest): bundler (real esbuild-wasm on a fixture prototype;
  error formatting), protocol path guard, design store event reducer, board
  layout, DesignPanel interactions (toast undo, nudge, tabs), double-buffer
  swap logic.
- Live smoke: run the dev app, start a recording, drive commands through the
  manual endpoints with a scripted transcript (fixture follower), confirm a
  bundle renders in the panel and the pop-out.

## Out of scope (v1)

Variants/alternatives, prototype ↔ board linking, speaker attribution,
non-Claude UI agents, Windows-specific QA of the pop-out.
