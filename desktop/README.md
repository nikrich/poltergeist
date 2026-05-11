# ghostbrain desktop

Electron app for ghostbrain (macOS + Windows). Slice 1 — shell only, no Python integration.

## Develop

    npm install
    npm run dev

## Test

    npm test          # vitest smoke test
    npm run typecheck
    npm run lint

## Build (Slice 5 fleshes this out)

    npm run build

## Layout

- `src/main/`       — Electron main process (window lifecycle, electron-store, dialogs)
- `src/preload/`    — typed contextBridge exposed as `window.gb`
- `src/renderer/`   — React 18 + Tailwind v4 + Zustand
  - `screens/`      — six screens (today, connectors, meetings, capture, vault, settings)
  - `components/`   — shared UI primitives + chrome
  - `stores/`       — zustand stores (navigation, meeting, settings, toast)
  - `lib/mocks/`    — stubbed data; replaced by Slice 3 with real Python sidecar data

## Slice 1 status

- All 6 screens render at design fidelity with stubbed data
- Theme + density + vault path persist via electron-store
- Recording state machine works (pre→recording→post) — UI only, no actual audio
- Buttons that would call into Python show a toast saying "wired in Slice N"
- macOS uses `hiddenInset` traffic lights; Windows uses native frame
- Cross-platform: ⌘ on Mac, Ctrl on Windows in hotkey display

## Known light-mode considerations

Most colors flip via CSS variables in `colors_and_type.css` (`:root` vs
`[data-theme="light"]`), so light mode is functional. Intentional fixed colors
— deep cool ink text on neon/oxblood buttons and brand accent fills (neon,
oxblood, moss) — stay the same in both themes by design. A manual visual
walkthrough of all six screens in light mode is recommended before shipping
to verify contrast at small font sizes (eyebrows, mono captions, pill text).

## Backend

The desktop app talks to a Python FastAPI sidecar at `127.0.0.1:<random>` over
localhost HTTP, using a Bearer token captured at startup. The sidecar lives
at `ghostbrain/api/` and is launched by Electron main as `python3 -m ghostbrain.api`.

In dev, you need:

    cd ..
    source .venv/bin/activate
    pip install -e ".[api]"

Then `npm run dev` from `desktop/` spawns the sidecar automatically. The sidecar
prints `READY port=<port> token=<hex>` as its first stdout line; Electron main
parses that to get the port and the auth token. The renderer never sees the
token — every `window.gb.api.request(...)` call is forwarded by main with the
correct Authorization header.

## Phase 1 status (Read Architecture)

- 9 read-only endpoints under `/v1/`: vault stats, connectors (list + detail),
  captures (list + detail), meetings, agenda, activity, suggestions. No writes yet.
- React Query v5 for fetch lifecycle on the renderer.
- Loading skeletons, empty states, error retry on every panel.
- Sidecar lifecycle: spawn on launch, auto-restart once on crash, graceful
  shutdown on quit.
- Token never leaves main process; renderer talks via IPC only.
- Connector list reflects what's actually in `ghostbrain/connectors/`
  (claude_code, github, jira, confluence, calendar, atlassian, slack, gmail).

## Phase 2 will add

- Write endpoints (sync now, start/stop recording, save to vault, ask the archive)
- WebSocket events channel (live transcript, sync progress)
- OAuth flows for connectors
- PyInstaller bundling so end users don't need Python installed
- Code signing + installer + auto-updater

## Slice 1 known TODOs (intentional)

These are deferred to later slices, not bugs:

- All connector data, vault counts, capture inbox, meeting history are mocks → Slice 3
- "start recording" produces no audio → Slice 4
- No code signing, no installer, no auto-update → Slice 5
- No real connector OAuth flows → Slice 3
