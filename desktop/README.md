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

## Slice 1 known TODOs (intentional)

These are deferred to later slices, not bugs:

- All connector data, vault counts, capture inbox, meeting history are mocks → Slice 3
- "start recording" produces no audio → Slice 4
- No code signing, no installer, no auto-update → Slice 5
- No real connector OAuth flows → Slice 3
