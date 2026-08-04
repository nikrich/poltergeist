# Ghostbrain Desktop — Slice 1.5: Hack Cleanup

**Date:** 2026-05-08
**Status:** drafted, pending approval
**Depends on:** Slice 1 (`feat/desktop-shell-slice-1`, PR #2)
**Author:** brainstormed with Jannik after Slice 1 PR review

## Context

Slice 1 shipped a working Electron + React shell, but it took several pragmatic shortcuts to land at design fidelity quickly:

- Inline `style={{}}` everywhere instead of using Tailwind v4 (which is installed and configured)
- `sandbox: false` on `webPreferences` to keep the preload bundle simple
- `electron-store` v10 (ESM) bundled into the CJS main bundle via a Vite externalize-exclude workaround
- Hand-rolled SVG construction in the `Lucide` component
- A `Platform` type-literal union duplicated in the renderer because `NodeJS.Platform` isn't visible there
- `data-density` attribute set on body but consumed by no CSS rule (dead code)
- 12+ settings toggles render with default state and no `onChange` (no persistence)
- Hex literals scattered through components (`#0E0F12`, `#FF6B5A`, `#A2C795`, etc.) that won't theme-flip
- No CSP, no input validation in IPC handlers, no ErrorBoundary, no app icon
- ESLint v9 install required `--legacy-peer-deps` due to a transitive `@eslint/js` peer pin

Slices 2–5 will layer real backend integration, recording, packaging on top. Doing those slices on top of these shortcuts compounds the cost — every screen migrated to real data would also need its inline styles refactored later. Cheaper to do the cleanup once now.

This slice is **strictly within `desktop/`**. The Python backend (`ghostbrain/` package, worker, connectors, recorder, console scripts, orchestration, tests) is **out of scope and must remain unmodified**. The cleanup-pass branch should pass `git diff main..HEAD -- ":!desktop"` showing zero non-desktop file changes.

## Goals

1. Remove every shortcut catalogued above, replacing each with the proper engineering choice.
2. Establish defensive infrastructure (ErrorBoundary, CSP, IPC input validation, app icon, window-state persistence, native menus) that Slices 2–5 will need but is currently absent.
3. Convert the renderer's styling layer from inline `style={{}}` to Tailwind classes consistently, so that future screens can be authored cleanly and the design tokens are the single source of color/type/spacing.
4. Wire the remaining settings toggles to real persistence — the *toggle component is real, the stored keys do not exist yet*.
5. Implement the `density` setting visually so it stops being dead code.
6. Audit and verify light-mode rendering across all six screens.

## Non-goals

- **No changes outside `desktop/`.** The Python backend stays exactly as it is.
- **No Slice-2-style backend integration.** Slice 2 builds the FastAPI sidecar; this slice does not.
- **No real data.** Mock data structure in `lib/mocks/` stays; Slice 3 replaces those files. This slice may *reorganize* the mock files for clarity, but the data contract stays.
- **No new connectors / connector logos.** Slice 3 reconciles the connector list against reality. This slice keeps the design's mock connector set.
- **No Slice 4 / Slice 5 work.** No recorder integration, no installer config, no signing.
- **No first-run wizard, no tray, no notifications, no global hotkeys, no quick-capture window.** Those are cross-cutting OS-integration features and belong in their own slice.
- **No real auth / account flow.** "theo · ghostbrain pro" stays hard-coded in Settings → Account; that gets replaced when an auth slice happens.
- **No new tests beyond what's needed to lock down the cleanup.** Real test coverage is a separate slice.

## Phases

The work splits into five phases that can be implemented in any order *except* Phase A (build foundation) which should land first because it changes config files everything else depends on.

### Phase A — Build foundation

Six small, independent fixes to project config:

1. **Replace `electron-store` with a hand-rolled JSON config wrapper.**
   - Remove `electron-store` from `package.json`.
   - Remove the `externalizeDepsPlugin({ exclude: ['electron-store'] })` workaround in `electron.vite.config.ts`; restore the plain `externalizeDepsPlugin()` for the main process.
   - Implement `src/main/settings.ts` as ~30 lines: read JSON from `app.getPath('userData') + '/config.json'`, write through atomically (write-tmp-then-rename), keep the same `getAll() / setKey<K>()` surface so the preload bridge contract is unchanged.
   - On schema migration: add a `version` field to the JSON, validate on read, fall back to defaults on mismatch.

2. **Re-enable the renderer sandbox.**
   - Set `sandbox: true` in `BrowserWindow` `webPreferences`.
   - Audit the preload (`src/preload/index.ts`): it currently imports only from `electron` (`contextBridge`, `ipcRenderer`) and the type-only `./types`. Both are sandbox-compatible. The current comment in `index.ts` claiming sandbox-true would force a polyfilled subset is overstated for our preload — it should work as-is. Verify by running and confirming the bridge still resolves.
   - Update the comment to reflect the new state ("`sandbox: true`; preload uses only electron's own APIs").

3. **Migrate `Lucide` to `lucide-react`.**
   - `npm uninstall lucide && npm install lucide-react`.
   - Replace `src/renderer/components/Lucide.tsx`'s manual `createElementNS` implementation with a thin wrapper: `import { icons } from 'lucide-react'; const Cmp = icons[camel]; return <Cmp size={...} color={...} ... />`. Keep the same prop shape so callers don't change.
   - The wrapper still degrades gracefully on unknown icon names: in development, `console.warn('Lucide: unknown icon name:', name)` and render an empty span. In production, just render an empty span.

4. **Resolve the renderer's `NodeJS.Platform` visibility.**
   - Create `src/shared/types.ts` (a new directory at `src/`).
   - Add a `tsconfig.shared.json` referenced by both `tsconfig.node.json` and `tsconfig.web.json`. The shared project includes `@types/node` *only* for the platform type.
   - Move `Settings`, `Theme`, `Density`, `GbBridge` into `src/shared/types.ts`. Update imports in main, preload, and renderer to point at `../shared/types` or `../../shared/types` as appropriate.
   - The local `Platform` literal-union goes away; renderer uses `NodeJS.Platform` directly.

5. **`WebkitAppRegion` CSS type augmentation.**
   - Create `src/shared/csstype.d.ts` with:
     ```ts
     import 'csstype';
     declare module 'csstype' {
       interface Properties {
         WebkitAppRegion?: 'drag' | 'no-drag';
       }
     }
     ```
   - Remove every `as React.CSSProperties` cast in `Sidebar.tsx` (and anywhere else that uses `WebkitAppRegion`).

6. **ESLint v9 + `@eslint/js` peer-dep.**
   - Audit current devDependencies. The `--legacy-peer-deps` workaround came from a transitive plugin pinning ESLint v8. Identify the offender: `npm ls eslint`.
   - If the plugin has a v9-compatible release available now, upgrade it.
   - If not, bring `@eslint/js` to whatever version the offender accepts (one version below works fine for our usage).
   - End state: `npm install` works without `--legacy-peer-deps`, recorded in CI script.

### Phase B — Style migration: inline → Tailwind

The renderer currently authors styles three ways: inline `style={{}}` objects (everywhere), Tailwind utility classes (in App.tsx and the loading state only), and the design-token CSS in `colors_and_type.css` plus `styles.css`. The mix is an artifact of porting speed, not intent.

Goal: every component and screen uses Tailwind utility classes whose values come from `@theme`. Remaining `style={{}}` is reserved for cases where:
- A value is genuinely dynamic per-render (radial-gradient positioning, computed color from a prop, `width: ${pct}%`).
- A CSS feature has no Tailwind equivalent (variable-font `fontVariationSettings`, custom `WebkitAppRegion`).

#### B.1 — Extend `@theme` to cover everything used in inline styles

Audit `colors_and_type.css` and `styles.css` against what the components use. Add the missing tokens to `@theme` in `styles.css`:

- Spacing scale (the design uses `4px / 8px / 12px / 14px / 16px / 24px / 32px / 48px / 64px` consistently — map to Tailwind's spacing scale or extend if needed)
- Font sizes (`fs-9`, `fs-10`, `fs-11`, `fs-12`, `fs-13`, `fs-14`, `fs-16`, `fs-20`, `fs-22`, `fs-26`, `fs-28`, `fs-32`, `fs-38`, `fs-72` are all used)
- Letter spacing (`-0.025em`, `-0.02em`, `-0.03em`, `-0.035em`, `0.12em`, `0.14em`)
- Line heights (`1.05`, `1.1`, `1.15`, `1.2`, `1.4`, `1.5`, `1.55`)
- Border radii beyond `sm/md/lg`: `2px`, `4px`, `6px`, `8px`, `10px`, `12px`, `999px`
- Z-indices (we use `1` and `1000`)
- Custom utilities for the recurring patterns: `.gb-eyebrow`, `.gb-mono-caption`, `.gb-display-h1`, etc.

Document each token with a short comment on its semantic meaning.

#### B.2 — Per-component migration

In dependency order (leaves first), migrate each component file from `style={{}}` to Tailwind classes plus theme tokens:

1. `Eyebrow.tsx`, `Pill.tsx`, `Toggle.tsx`, `Catch.tsx`, `Ghost.tsx` — small, leaf-level
2. `Btn.tsx` — variants and sizes become composable Tailwind classes (use `clsx` or string concat); hover state via `hover:bg-neon-dark` instead of `useState`
3. `Lucide.tsx` — after Phase A.3, this is a thin `lucide-react` wrapper with only `width/height/color` props; trivial
4. `Panel.tsx`, `TopBar.tsx`, `StatusBar.tsx`, `WindowChrome.tsx`, `Toaster.tsx`
5. `Sidebar.tsx` — has dynamic active-state styling; the active branch uses `bg-neon/12 text-ink-0` etc. Pull the absolute-positioned active indicator bar out into its own simple class.
6. Screens: `today.tsx`, `connectors.tsx`, `meetings.tsx`, `capture.tsx`, `vault.tsx`, `settings.tsx`. Largest files; do them last when the component-level patterns are settled.

Two concrete substitutions to follow throughout:

- `style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-2)' }}` → `className="font-mono text-[11px] text-ink-2"`
- `style={{ background: hover ? 'var(--bg-vellum)' : 'transparent' }}` → `className="hover:bg-vellum bg-transparent"` (drops the `useState` hover state entirely)

#### B.3 — Audit and replace hex literals

After B.2, run `git grep -E "#[0-9A-Fa-f]{3,8}" src/renderer/`. Every match needs to be either:

- A theme token (most cases): replace with the corresponding `@theme` variable / Tailwind class
- A *deliberately fixed* color (like the neon `#0E0F12` text on a primary button — that color is intentionally always-dark regardless of theme): keep as-is but document with a one-line comment naming the semantic meaning ("primary button text — always dark, neon background reads at WCAG AA against #0E0F12 in both themes")
- A duplicate of an existing token: removed in favor of the token

Outcome: zero "anonymous" hex literals; every fixed color is either tokenized or commented as intentional.

#### B.4 — Verify light mode across all six screens

Manually walk through each screen with `theme = 'light'`. Take notes on visual breaks (dark text on light background that's now invisible, missing contrast, wrong border colors). Fix each.

This step likely surfaces 5–15 small theming bugs. Track them in a checklist as you go and fix as you find them.

### Phase C — Settings correctness

#### C.1 — Wire all settings toggles to real persistence

Today: 12+ `<Toggle on />` calls render with default state and no `onChange`. They look interactive but mutate nothing.

Extend the `Settings` schema in `src/shared/types.ts` with the new keys:

```ts
interface Settings {
  // existing
  theme: Theme;
  density: Density;
  vaultPath: string;

  // new (all default true unless otherwise noted)
  dailyNoteEnabled: boolean;
  markdownFrontmatter: boolean;
  autoLinkMentions: boolean;

  cloudSync: boolean;             // default false
  e2eEncryption: boolean;
  telemetry: boolean;             // default false
  llmProvider: 'local' | 'anthropic' | 'openai';  // default 'local'

  autoRecordFromCalendar: boolean;
  diarizeSpeakers: boolean;
  extractActionItems: boolean;
  audioRetention: '30d' | '7d' | 'immediate' | 'forever';  // default '30d'
  transcriptModel: 'whisper-large-v3' | 'whisper-medium';

  folderStructure: 'by-source' | 'by-date' | 'by-person';  // default 'by-source'
}
```

Update `src/main/settings.ts` defaults to include them. Migration: on first read after upgrade, missing keys fall back to defaults and get persisted.

In `screens/settings.tsx`, replace `<Toggle on />` (uncontrolled with default) with controlled `<Toggle on={settings.X} onChange={(v) => setSetting('X', v)} />` for every row. Replace stub `<select onChange={() => stub(3)}>` with controlled selects that read and write the corresponding setting.

These settings are *persisted on disk* but **don't change app behavior** until Slice 3+ wires them. Document this with a short subtitle on each setting like "(takes effect when sync ships)" — or just trust that the toggle accurately reflects the user's intent and pretend it works for now. Either approach is honest; pick one and apply consistently.

#### C.2 — Implement `density`

Today: `data-density` is set on body, consumed by nothing.

Implement compact-vs-comfortable spacing rules as utility classes that apply only when `[data-density="compact"]` is the body. Affected surfaces:

- Sidebar nav row: comfortable `py-2` → compact `py-1`
- Top bar height: comfortable `56px` → compact `48px`
- Panel header padding: comfortable `12px 16px` → compact `8px 12px`
- Panel body padding: comfortable `12px` → compact `8px`
- Status bar height: comfortable `26px` → compact `22px`
- Settings rows: comfortable `14px 0` → compact `10px 0`

Author these as Tailwind component classes in `styles.css`:

```css
.gb-row { @apply py-2; }
[data-density="compact"] .gb-row { @apply py-1; }
```

…and apply `.gb-row` (etc.) in the components instead of inline padding.

Test by toggling the setting and seeing the layout actually contract.

#### C.3 — Account section honest

The Account section hard-codes "theo · ghostbrain pro". Until real auth lands (separate slice), replace this with one of:

a) **Honest empty state**: "Sign in is coming in a future release. ghostbrain runs locally for now — no account needed." With a small disabled "manage" button.

b) **Hidden**: drop the Account section from the nav until auth ships.

Pick (a). It tells the user the truth and reserves the UI real estate.

The "Connected devices" and "Sign out" rows go away with this change (they presume an account exists).

### Phase D — Defensive infrastructure

Six items, each small:

#### D.1 — `ErrorBoundary` at the App root

Implement `src/renderer/components/ErrorBoundary.tsx` as a class component that catches render errors in its subtree, displays a centered "Something went wrong" panel with the error message and a "Reload" button (calls `location.reload()`).

Wrap the entire `<App />` tree in main.tsx:

```tsx
createRoot(container).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
);
```

In dev mode, also `console.error` the error and component stack.

#### D.2 — Content-Security-Policy

Add to `src/renderer/index.html` `<head>`:

```html
<meta http-equiv="Content-Security-Policy"
      content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self';" />
```

`'unsafe-inline'` for styles is regrettable but unavoidable while we still have *any* inline styles (and the `<style>` blocks generated by Tailwind). After Phase B completes most of the inline styles, we may be able to tighten this further.

The Google Fonts host is allowed because `colors_and_type.css` `@imports` JetBrains Mono from Google. After Phase A optionally bundles JetBrains Mono locally, that allowance can be dropped.

Verify in dev that nothing breaks (no console CSP violations).

#### D.3 — IPC handler input validation

Today: `ipcMain.handle('gb:settings:set', (_e, key, value) => settings.setKey(key, value as never))` — accepts any string for `key` and any value, no validation.

Add a small zod (or hand-rolled equivalent — zod is the standard, install it: `npm install zod`) schema for the `Settings` shape. In each handler:

```ts
ipcMain.handle('gb:settings:set', (_e, key, value) => {
  const result = settingsSchema.shape[key]?.safeParse(value);
  if (!result?.success) {
    return { ok: false, error: `Invalid value for ${key}` };
  }
  settings.setKey(key, value);
  return { ok: true };
});
```

The bridge return type changes from `Promise<void>` to `Promise<{ ok: true } | { ok: false; error: string }>`. Renderer updates accordingly: `useSettings.set` returns the result and surfaces errors as toasts.

For `gb:shell:openPath`: validate the path is a string starting with the user's `vaultPath` (no escaping outside the vault). Return error if not.

For `gb:dialogs:pickVaultFolder`: no input to validate; the return value is fine.

#### D.4 — App icon

Design a 1024×1024 master icon (the Ghost glyph on a dark cool-ink background; eyes positioned per the design). Generate:

- `desktop/build/icon.png` (1024×1024)
- `desktop/build/icon.icns` (Mac, generated via `iconutil` from a 6-density iconset)
- `desktop/build/icon.ico` (Windows, multi-resolution: 256, 128, 64, 32, 16)
- `desktop/build/icon@2x.png` for the dock

Reference these from `electron-builder.yml`. In dev, set the `BrowserWindow` icon explicitly: `icon: join(__dirname, '../../build/icon.png')`.

#### D.5 — Window state persistence

Currently the window opens at 1280×800 every time. Persist position + size + maximized state across launches.

Either install `electron-window-state` (small, vetted) or roll a 30-line equivalent that uses the same JSON config wrapper from Phase A.1. Restore on `whenReady`, save on `move`/`resize`/`close`.

Ignore the persisted state if it's off-screen (monitor disconnected); fall back to defaults.

#### D.6 — Native menu bar

Set the Electron menu via `Menu.setApplicationMenu` in `src/main/index.ts`. Use `Menu.buildFromTemplate` with the standard template:

- macOS: app menu (About, Preferences→opens settings screen, Hide, Quit), Edit (Undo/Redo/Cut/Copy/Paste/Select All), View (Reload — dev only, Toggle DevTools — dev only, Toggle Full Screen), Window (Minimize, Zoom), Help.
- Windows / Linux: File (Quit), Edit (Cut/Copy/Paste), View (same as Mac sans dev items in prod), Help.

"Preferences" / "Settings" item sends a custom IPC event `gb:nav:settings` that the renderer listens for and uses to set `useNavigation.active = 'settings'`.

This adds a real menu instead of Electron's default. Cmd+, on Mac opens Settings (matches macOS convention).

### Phase E — Toaster: real errors, not just stubs

Currently the `useToasts` store is used only by `stub(N)` to fire "wired in Slice N" messages.

Extend it to handle three toast types:

```ts
type ToastKind = 'info' | 'success' | 'error';
interface Toast { id: number; kind: ToastKind; message: string; }
```

Add `toast.error(message)`, `toast.success(message)`, `toast.info(message)` helpers. The Toaster renders kind-aware styling (oxblood border for errors, neon for success, plain for info).

The new IPC error returns from D.3 surface via `toast.error(...)`. ErrorBoundary's "Something went wrong" path also fires a toast in addition to the full-screen state.

`stub(N)` keeps working (becomes `toast.info('wired in Slice N')` internally).

## Acceptance criteria

The cleanup-pass branch is done when:

1. **No code outside `desktop/` has changed.** `git diff main..HEAD -- ":!desktop"` shows zero file changes.
2. **`sandbox: true`** in `BrowserWindow`; app boots and the bridge resolves.
3. **`electron-store` removed** from dependencies; `npm ls electron-store` returns nothing.
4. **`externalizeDepsPlugin()` is called with no `exclude`** in the main config.
5. **`lucide-react` replaces `lucide`**; the manual `createElementNS` is gone.
6. **`src/shared/types.ts` exists**; imports resolve from main, preload, and renderer; no duplicated `Platform` literal union.
7. **`as React.CSSProperties` casts are gone** wherever `WebkitAppRegion` was the only reason for them.
8. **`npm install` works without `--legacy-peer-deps`**.
9. **`git grep "style={{" src/renderer/components/ src/renderer/screens/`** returns only justified cases (radial gradients, dynamic widths, variable-font, app-region) — every other inline style migrated to Tailwind.
10. **`git grep -E "#[0-9A-Fa-f]{3,8}" src/renderer/`** returns only commented intentional fixed colors. Zero anonymous hex literals.
11. **All six screens render correctly in light mode** (manual walkthrough; no obvious breaks).
12. **Every `<Toggle>` and `<select>` in Settings is controlled** and persists. Restart-and-verify works for at least three randomly-chosen settings.
13. **Density toggle has visible effect** across sidebar, top bar, panels, status bar, settings rows.
14. **Account section** shows the honest "sign-in coming later" empty state; "Connected devices" and "Sign out" rows are gone.
15. **`ErrorBoundary`** wraps `<App />`; throwing in a child component shows the fallback panel instead of a white screen.
16. **CSP meta tag** present in `index.html`; no console violations during a normal session.
17. **IPC handlers reject invalid input** with `{ ok: false, error }`. Specific test: send `set('theme', 'rainbow')` from the renderer dev console and observe the rejection.
18. **App icon** appears in the dock (Mac) and taskbar (Win); window icon set in dev.
19. **Window state persists** across quit + relaunch.
20. **Native menu bar** present; `Cmd+,` (Mac) navigates to Settings; standard Edit menu shortcuts work in any text input.
21. **`toast.error / success / info`** helpers exist; ErrorBoundary's path surfaces a toast as well as the fullscreen state.
22. **`npm run typecheck && npm run lint && npm test`** all pass.
23. **`npm run dev`** boots cleanly on macOS (visual confirmation).

## Risks & open questions

- **Phase B (style migration) is the longest and most error-prone.** It touches every file. Some inline styles encode behavior (hover states, conditional rendering) that doesn't translate 1:1 to utility classes. Allow a buffer for surprises.
- **Light-mode audit (B.4)** will surface bugs we haven't seen because nobody has clicked through every screen in light mode. Not a blocker; track and fix as found.
- **CSP `'unsafe-inline'` for styles** stays for now because some inline styles will remain (radial gradients) and Tailwind's runtime style injection sometimes requires it. Acceptable for slice 1.5; tighten in a later slice.
- **Phase C.1 settings expansion** introduces persisted state for keys that don't yet drive behavior. If we change our minds about a key (e.g. drop telemetry entirely), users will have stale data. Mitigated by the schema-version field added in Phase A.1.
- **`sandbox: true` may not actually work** if there's a hidden Node import in the preload chain we missed. If it breaks, the fix is either to find and remove the import, or to revert and document specifically what required sandbox-false. Don't paper over it.
