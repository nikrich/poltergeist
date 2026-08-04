# Ghostbrain Desktop — Slice 1: Shell

**Date:** 2026-05-08
**Status:** approved, ready for implementation plan
**Author:** brainstormed with Jannik

## Context

Ghostbrain is a local-first personal knowledge automation system written in Python. A desktop-app design was produced in Claude Design (`/desktop` currently holds the raw HTML/JSX/CSS prototype). We are building this as a real production app for macOS and Windows.

Total scope is split into 5 slices, each with its own spec:

| # | Slice | Notes |
|---|---|---|
| 1 | **Shell** | This spec — Electron scaffold, all 6 screens at design fidelity, settings persistence, no Python integration |
| 2 | Python bridge | Local FastAPI sidecar spawned by Electron, typed IPC |
| 3 | Real data | Today/Connectors/Capture/Settings read from real vault + state dir; reconcile connector list |
| 4 | Recorder | Pre/Live/Post wired to `ghostbrain.recorder`, cross-platform audio |
| 5 | Packaging | PyInstaller sidecar, electron-builder for Mac (.dmg, notarized) + Win (.exe, signed), auto-updater |

Long-term direction: implement against the existing Python codebase via a bridge first; a full backend rewrite is a future phase, not blocking shell work.

## Goals (Slice 1)

1. Render all 6 design screens at full visual fidelity in a real Electron app on macOS and Windows.
2. Replace the design-tool tweaks panel with real, persisted user settings (theme, density, vault path).
3. Establish a project structure that subsequent slices can extend without restructuring.
4. Ship nothing that mocks the user — buttons that would call into Python show an explicit "wired in Slice 2" toast rather than fake success.

## Non-goals (Slice 1)

- No Python sidecar, no IPC beyond settings get/set.
- No real audio capture; the recording state machine is UI-only.
- No code signing, no installer, no auto-update.
- No real connector OAuth flows; connector toggles are visual.
- No tests beyond a smoke test that App renders. Real test investment lands in Slice 3.

## Stack

- **Electron** (latest stable) with `electron-vite` for the build pipeline.
- **React 18** + **TypeScript** in strict mode.
- **Tailwind v4** with design tokens declared via CSS `@theme`. The existing `colors_and_type.css` is the source of truth for tokens; Tailwind reads them via `@theme` so utilities like `bg-paper`, `text-ink-0`, `text-neon` work without re-declaring values.
- **Zustand** for cross-screen state (navigation, recording status, settings).
- **electron-store** for persistent settings on disk, exposed to the renderer via a typed preload bridge.
- **Vitest + React Testing Library** wired up; smoke test only in Slice 1.
- **ESLint + Prettier** standard configs.

Rationale for Tailwind v4 over v3: v4's CSS-first `@theme` config meshes naturally with the existing `colors_and_type.css` — we can keep that file as the design-token source instead of duplicating values into `tailwind.config.ts`.

## Repository layout

The desktop app lives at `desktop/` (repo root), as an independent npm workspace. Not `apps/desktop/` — there is only one app, the extra nesting buys nothing.

```
desktop/
├── package.json
├── tsconfig.json
├── electron.vite.config.ts
├── electron-builder.yml          # placeholder; populated in Slice 5
├── src/
│   ├── main/
│   │   ├── index.ts              # window lifecycle, hiddenInset on Mac
│   │   └── settings.ts           # electron-store wrapper
│   ├── preload/
│   │   └── index.ts              # typed bridge: window.gb.settings.{get,set}
│   └── renderer/
│       ├── index.html
│       ├── main.tsx
│       ├── App.tsx
│       ├── styles.css            # @import tailwind, @theme tokens, signature animations
│       ├── components/           # Btn, Pill, Lucide, Ghost, Panel, Sidebar, TopBar, StatusBar
│       ├── screens/              # today, connectors, meetings, capture, vault, settings
│       ├── stores/               # navigation, settings, meeting
│       └── lib/
│           └── mocks/            # all hard-coded sample data, one module per screen
├── assets/                       # connector svgs, glyph, favicon
└── fonts/                        # GoogleSansFlex variable font
```

As the first step of implementation, the current contents of `desktop/` (the raw HTML prototype) move under `desktop/_prototype/` as a reference for visual parity. They are deleted at the end of Slice 1, before the slice is merged.

## Window chrome

- **macOS:** `BrowserWindow` opened with `titleBarStyle: 'hiddenInset'` and `trafficLightPosition` adjusted to sit cleanly inside the sidebar's top-left. The sidebar's existing top-of-pane spacing already accommodates them.
- **Windows / Linux:** native frame (default). The custom titlebar dots in the design are replaced by the OS titlebar.
- Default size **1280 × 800**, minimum **1024 × 720**.
- The sidebar uses `-webkit-app-region: drag` on its non-interactive surfaces, with `-webkit-app-region: no-drag` on every clickable element. This is identical to the current prototype's approach and works for both `hiddenInset` Mac and native Win frames.

## State management

Three Zustand stores, each in `src/renderer/stores/`:

- **`useNavigation`** — `{ activeScreen: ScreenId; setActiveScreen(id): void }`
- **`useSettings`** — `{ theme: 'dark' | 'light'; density: 'comfortable' | 'compact'; vaultPath: string; ... setX() }`. Reads initial state from the preload bridge on app boot; every `setX` writes through to electron-store.
- **`useMeetingState`** — `{ phase: 'pre' | 'recording' | 'post'; elapsed: number; start(); stop() }`. UI-only in Slice 1; in Slice 4, the `start`/`stop` methods become bridge calls to `ghostbrain.recorder`.

No router. Navigation is a `screenId` in a Zustand store; `App.tsx` switch-cases on it. There are 6 screens — `react-router` is overkill.

## Settings persistence

Settings live at the OS-default location chosen by `electron-store`: `~/Library/Application Support/ghostbrain/config.json` on macOS, `%APPDATA%/ghostbrain/config.json` on Windows. Schema (Slice 1):

```ts
type Settings = {
  theme: 'dark' | 'light';
  density: 'comfortable' | 'compact';
  vaultPath: string;             // default: '~/ghostbrain/vault' resolved
  // future slices add: connectorState, recorderConfig, hotkeys, etc.
};
```

The preload exposes a typed API:

```ts
window.gb.settings.get(): Promise<Settings>
window.gb.settings.set<K extends keyof Settings>(key: K, value: Settings[K]): Promise<void>
```

The renderer never touches `electron-store` directly — only through the bridge.

## Replacing the tweaks panel

The prototype's tweaks panel goes away entirely. Each tweak maps to real product surface:

| Tweak | Replacement |
|-------|-------------|
| `theme` | Settings → Display → Theme (segmented control: dark / light) |
| `density` | Settings → Display → Density (segmented control: comfy / compact) |
| `screen` | Real sidebar navigation |
| `recording` | Real button in Meetings screen header (state machine in `useMeetingState`) |
| `showNoise` | Dropped — noise overlay is always on; this was a dev aid |

## Mock data

Every screen in the prototype has hard-coded sample data inline. In Slice 1 this gets extracted into `src/renderer/lib/mocks/<screen>.ts`, one file per screen. This isolates Slice 3's real-data swap to data-layer changes — the components themselves stay stable.

## Connector list

Slice 1 keeps the design's mock connector set (`gmail`, `slack`, `notion`, `linear`, `calendar`, `github`, `drive`) for visual fidelity. The connector list is data-driven from `lib/mocks/connectors.ts`.

In Slice 3 this file is replaced (not edited; replaced) with the real connector set — `claude_code`, `github`, `jira`, `confluence`, `calendar`, `atlassian` — pulled from the Python sidecar. Component code does not change between Slice 1 and Slice 3.

This means in Slice 3 we will need SVG logos for `claude_code`, `jira`, `confluence`, `atlassian` (the rest exist in `assets/connectors/` already). Tracking that as a Slice 3 prerequisite, not Slice 1.

## Stub policy for actions

Buttons that would call into Python in later slices show a transient toast saying "wired in Slice 2" (or 3, 4, etc., as appropriate), then no-op. Specifically:

- `start recording`, `stop recording`, `pause` (meetings) — Slice 4
- `sync now`, `connect`, `pause`, `disconnect`, `reauthorize` (connectors) — Slice 3
- `save to vault`, `share md`, `play audio` (post-meeting) — Slice 4
- `open in obsidian` (vault) — Slice 3 (uses Electron's `shell.openPath`)
- `ask the archive` (today, capture) — Slice 3
- `change vault path` (settings) — actually wired in Slice 1 (just a folder picker via `dialog.showOpenDialog`, persists through electron-store)

State changes that are pure UI (e.g. the recording state machine cycling pre→live→post via the existing buttons) work as visual transitions in Slice 1, but produce no real artifacts.

## Tests

- **Smoke test** — `App` renders without throwing. Run in CI.
- **No screen-level tests in Slice 1** — the screens are stubs over mock data; tests would just assert the mocks render. Real test investment lands in Slice 3 alongside real data.
- ESLint + TypeScript strict mode enforced in CI as a stand-in for behavioral tests.

## Cross-platform considerations (Slice 1 only)

- **Fonts:** the GoogleSansFlex variable font ships in `desktop/fonts/`. CSS `@font-face` with the existing settings — works on both OSes.
- **Native menus:** standard application menu on Mac (Edit/View/Window/Help with default roles), no Windows menubar customization.
- **Keyboard:** ⌘ on Mac, Ctrl on Windows. Hotkeys section in settings shows the right modifier per platform (using a `formatShortcut(platform, key)` helper).
- **Path display:** all path strings shown in the UI use the OS path separator. `vaultPath` from electron-store is resolved on the main side and rendered on the renderer side using `path.sep`.

## Out of scope, called out explicitly

These are easy to accidentally over-build into Slice 1. They belong to later slices:

- Connector OAuth — Slice 3.
- Audio device enumeration in the meetings pre-screen — design has it; Slice 4.
- Speech-to-text and live transcript — Slice 4.
- Vault initialization wizard for first-run users — separate slice, post-1.
- Telemetry, crash reporting — Slice 5 (or never).
- Update channel selection — Slice 5.

## Acceptance criteria

Slice 1 is done when:

1. `npm run dev` from `desktop/` launches the app on Mac and Windows. (The desktop app is a standalone npm project at `desktop/`, not part of a monorepo workspace.)
2. All 6 screens render at full visual fidelity vs. the prototype, with the only intentional deviations being the window chrome (Slice 1 design choice) and the tweaks-panel removal.
3. Theme switching works and persists across restart.
4. Density switching works and persists across restart.
5. Vault path picker works and persists across restart.
6. Recording state machine cycles pre→live→post via the meeting screen's own buttons; this works on both OSes.
7. Sidebar navigation works.
8. Stub-action toasts appear for every button labeled in the "Stub policy" section.
9. CI passes: TypeScript strict, ESLint clean, smoke test green.
10. No Python process is spawned, no network calls leave the box.
