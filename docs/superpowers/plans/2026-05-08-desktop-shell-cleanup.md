# Ghostbrain Desktop Shell — Slice 1.5 Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every shortcut Slice 1 took and stand up the defensive infrastructure (CSP, ErrorBoundary, IPC validation, native menus, window-state persistence, app icon, real settings persistence, real density, real toast kinds) that subsequent slices will need.

**Architecture:** All changes scoped strictly to `desktop/`. The Python backend (`ghostbrain/` package, scripts, orchestration, tests, pyproject.toml, root README, CLAUDE.md) is **off-limits** — no plan task may modify it. Hand-rolled JSON config replaces electron-store. Renderer sandbox re-enables. Tailwind v4 (already installed) replaces inline styles via expanded `@theme` tokens. Shared types live in `src/shared/` so renderer and main can both reference them without duplicating.

**Tech Stack:** No new framework choices. Adds: `lucide-react`, `zod`, possibly `electron-window-state`. Removes: `lucide`, `electron-store`.

**Spec:** `docs/superpowers/specs/2026-05-08-desktop-shell-cleanup-design.md`

**Hard rule for every task:** every commit must satisfy `git diff main..HEAD -- ":!desktop"` returns nothing. If you find yourself wanting to edit a file outside `desktop/`, stop — that's out of scope.

---

## File Structure

Files created:

| Path | Responsibility |
|------|----------------|
| `desktop/src/shared/types.ts` | `Theme`, `Density`, `Settings`, `GbBridge` shared between main/preload/renderer |
| `desktop/src/shared/csstype.d.ts` | Augments `csstype` with `WebkitAppRegion` so React style props accept it |
| `desktop/src/shared/settings-schema.ts` | `zod` schema mirroring the `Settings` interface; used by main IPC handler for input validation |
| `desktop/tsconfig.shared.json` | Composite project for `src/shared/`; included from both node and web tsconfigs |
| `desktop/src/main/window-state.ts` | Persist + restore window position/size/maximized across launches |
| `desktop/src/main/menu.ts` | Native application menu (macOS conventions, cross-platform fallback) |
| `desktop/src/renderer/components/ErrorBoundary.tsx` | Class-component error boundary at App root |
| `desktop/build/icon.png` | 1024×1024 master app icon |
| `desktop/build/icon.icns` | macOS multi-density icon |
| `desktop/build/icon.ico` | Windows multi-resolution icon |

Files modified:

| Path | What changes |
|------|--------------|
| `desktop/package.json` | dep swaps: drop `electron-store`, `lucide`; add `lucide-react`, `zod`; possibly `electron-window-state` |
| `desktop/electron.vite.config.ts` | drop the `electron-store` exclude workaround |
| `desktop/src/main/settings.ts` | hand-rolled JSON config wrapper |
| `desktop/src/main/dialogs.ts` | (no behavior change; type imports update) |
| `desktop/src/main/index.ts` | `sandbox: true`, IPC handlers return validated results, mount window-state + menu, set BrowserWindow icon |
| `desktop/src/preload/index.ts` | type imports point at `../shared/types`; bridge return types reflect IPC validation result |
| `desktop/src/renderer/components/*.tsx` | Tailwind migration; ErrorBoundary added |
| `desktop/src/renderer/screens/*.tsx` | Tailwind migration; settings toggles wired to real keys; Account section honest empty state |
| `desktop/src/renderer/stores/settings.ts` | extends `Settings` with new keys; `set` returns validation result |
| `desktop/src/renderer/stores/toast.ts` | adds `kind` (info/success/error) + helpers |
| `desktop/src/renderer/components/Toaster.tsx` | renders kind-aware styling |
| `desktop/src/renderer/main.tsx` | wraps `<App />` in `<ErrorBoundary>` |
| `desktop/src/renderer/index.html` | adds CSP `<meta>` |
| `desktop/colors_and_type.css` and `desktop/src/renderer/styles.css` | extend `@theme` tokens; add density CSS rules |

Files deleted:

| Path | Why |
|------|-----|
| `desktop/src/preload/types.ts` | Content moves to `desktop/src/shared/types.ts` |

---

## Task ordering

Phases run A → B → C → D → E. Within Phase A all six tasks are independent (any order). Phase B's eight tasks must run in this order: B.1 (tokens) → B.2.* (component & screen migrations) → B.3 (hex audit) → B.4 (light-mode walkthrough). Phases C/D/E can run in any order once A is done; the plan presents one linear ordering.

---

## Task A.1: Replace electron-store with hand-rolled JSON config

**Files:**
- Modify: `desktop/package.json`
- Modify: `desktop/electron.vite.config.ts`
- Modify: `desktop/src/main/settings.ts`
- Test: `desktop/src/main/settings.test.ts` (new)

- [ ] **Step A.1.1: Remove electron-store**

```bash
cd desktop
npm uninstall electron-store
```

Verify `package.json` no longer lists `electron-store`.

- [ ] **Step A.1.2: Drop the externalize-deps workaround**

Edit `desktop/electron.vite.config.ts`. Replace:

```ts
plugins: [externalizeDepsPlugin({ exclude: ['electron-store'] })],
```

With:

```ts
plugins: [externalizeDepsPlugin()],
```

(Remove the explanatory comment block above the call as well — it's no longer relevant.)

- [ ] **Step A.1.3: Write a test for the JSON config wrapper**

Create `desktop/src/main/settings.test.ts`:

```ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

let workDir: string;

vi.mock('electron', () => ({
  app: { getPath: () => workDir },
}));

beforeEach(() => {
  workDir = mkdtempSync(join(tmpdir(), 'gb-settings-'));
  vi.resetModules();
});

afterEach(() => {
  rmSync(workDir, { recursive: true, force: true });
});

describe('settings store', () => {
  it('returns defaults when no file exists', async () => {
    const { getAll } = await import('./settings');
    const s = getAll();
    expect(s.theme).toBe('dark');
    expect(s.density).toBe('comfortable');
    expect(s.vaultPath).toMatch(/ghostbrain[/\\]vault$/);
  });

  it('persists set values to disk and reads them back', async () => {
    const { getAll, setKey } = await import('./settings');
    setKey('theme', 'light');
    expect(existsSync(join(workDir, 'config.json'))).toBe(true);
    const onDisk = JSON.parse(readFileSync(join(workDir, 'config.json'), 'utf-8'));
    expect(onDisk.theme).toBe('light');
    expect(getAll().theme).toBe('light');
  });

  it('merges defaults with on-disk values when a key is missing', async () => {
    const { writeFileSync } = await import('node:fs');
    writeFileSync(join(workDir, 'config.json'), JSON.stringify({ version: 1, theme: 'light' }));
    const { getAll } = await import('./settings');
    expect(getAll().theme).toBe('light');
    expect(getAll().density).toBe('comfortable');
  });

  it('falls back to defaults on corrupt JSON', async () => {
    const { writeFileSync } = await import('node:fs');
    writeFileSync(join(workDir, 'config.json'), '{ not valid json');
    const { getAll } = await import('./settings');
    expect(getAll().theme).toBe('dark');
  });
});
```

Update `desktop/vitest.config.ts` `include` to also pick up `src/main/**/*.test.ts`:

```ts
include: ['src/renderer/**/*.test.{ts,tsx}', 'src/main/**/*.test.ts'],
```

- [ ] **Step A.1.4: Run the test, watch it fail**

```bash
cd desktop
npm test
```

Expected: 4 new failures in `settings.test.ts` (the new behavior isn't there yet — `electron-store` is gone, the file imports something that doesn't exist).

- [ ] **Step A.1.5: Implement the JSON config wrapper**

Replace `desktop/src/main/settings.ts` entirely with:

```ts
import { app } from 'electron';
import { existsSync, readFileSync, writeFileSync, renameSync, mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, dirname } from 'node:path';
import type { Settings } from '../shared/types';

const SCHEMA_VERSION = 1;

interface OnDisk extends Settings {
  version: number;
}

const defaults: Settings = {
  theme: 'dark',
  density: 'comfortable',
  vaultPath: join(homedir(), 'ghostbrain', 'vault'),
};

function configPath(): string {
  return join(app.getPath('userData'), 'config.json');
}

function read(): Settings {
  const path = configPath();
  if (!existsSync(path)) return { ...defaults };
  try {
    const raw = readFileSync(path, 'utf-8');
    const parsed = JSON.parse(raw) as Partial<OnDisk>;
    if (parsed.version !== SCHEMA_VERSION) return { ...defaults };
    return { ...defaults, ...parsed };
  } catch {
    return { ...defaults };
  }
}

function writeAtomic(value: Settings): void {
  const path = configPath();
  mkdirSync(dirname(path), { recursive: true });
  const tmp = path + '.tmp';
  const payload: OnDisk = { ...value, version: SCHEMA_VERSION };
  writeFileSync(tmp, JSON.stringify(payload, null, 2), 'utf-8');
  renameSync(tmp, path);
}

let cache: Settings | null = null;

export function getAll(): Settings {
  if (cache === null) cache = read();
  return { ...cache };
}

export function setKey<K extends keyof Settings>(key: K, value: Settings[K]): void {
  if (cache === null) cache = read();
  cache = { ...cache, [key]: value };
  writeAtomic(cache);
}
```

> Note: this assumes `src/shared/types.ts` exists. Task A.4 creates it. If A.4 hasn't run yet, temporarily import from `../preload/types`. If you're running tasks in order A.1 → A.4, switch the import in A.4. The simplest path: do A.4 before this step, or accept the temporary import.

For this task, write the import as `from '../preload/types'` and let A.4 update it.

- [ ] **Step A.1.6: Run tests again, watch them pass**

```bash
cd desktop
npm test
```

Expected: settings.test.ts: 4 passed.

- [ ] **Step A.1.7: Verify the app still boots**

```bash
npm run dev
```

(Background, ~10s, kill.) Expected: clean boot. The settings file lives at `~/Library/Application Support/ghostbrain-desktop/config.json` on Mac.

- [ ] **Step A.1.8: Commit**

```bash
git add desktop/
git commit -m "refactor(desktop): replace electron-store with hand-rolled json config

Drops the v10 ESM dep and the externalizeDepsPlugin exclude workaround.
Schema is versioned, writes are atomic, missing keys fall back to defaults,
corrupt JSON falls back to defaults."
```

---

## Task A.2: Re-enable the renderer sandbox

**Files:**
- Modify: `desktop/src/main/index.ts`

- [ ] **Step A.2.1: Set sandbox: true and update the comment**

Edit `desktop/src/main/index.ts`. Locate the `webPreferences` block and replace:

```ts
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      // electron-vite ships preloads as CommonJS importing from `electron`;
      // sandbox: true would force a polyfilled subset that doesn't bundle
      // cleanly. contextIsolation: true above is what actually keeps the
      // renderer at arm's length, and our preload exposes only a typed
      // bridge to electron's own APIs — no remote content, no fs access.
      sandbox: false,
    },
```

With:

```ts
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: true,
    },
```

- [ ] **Step A.2.2: Verify the bridge still works**

```bash
cd desktop
npm run dev
```

(Background, ~10s.) Open the Electron window's DevTools (View → Toggle Developer Tools, or Cmd+Opt+I) and at the console run:

```js
window.gb.settings.getAll().then(console.log);
```

Expected: returns an object with `theme`, `density`, `vaultPath`. If it errors out — typically with `Cannot find module 'electron'` or a sandbox violation — note the exact error and STOP. Do not paper over with `sandbox: false`. The error tells you which sandbox-incompatible thing slipped into the preload chain.

If everything works, kill dev.

- [ ] **Step A.2.3: typecheck and test**

```bash
npm run typecheck
npm test
```

Both should pass.

- [ ] **Step A.2.4: Commit**

```bash
git add desktop/src/main/index.ts
git commit -m "feat(desktop): re-enable renderer sandbox

contextIsolation alone was carrying the security weight; the preload only
imports from electron's own APIs which works under the sandboxed polyfill.
The earlier sandbox:false was a Slice 1 shortcut, not a load-bearing choice."
```

---

## Task A.3: Migrate Lucide to lucide-react

**Files:**
- Modify: `desktop/package.json`
- Modify: `desktop/src/renderer/components/Lucide.tsx`

- [ ] **Step A.3.1: Swap deps**

```bash
cd desktop
npm uninstall lucide
npm install lucide-react
```

- [ ] **Step A.3.2: Replace the Lucide component**

Replace `desktop/src/renderer/components/Lucide.tsx` entirely with:

```tsx
import * as icons from 'lucide-react';

interface Props {
  name: string;
  size?: number;
  color?: string;
  style?: React.CSSProperties;
  className?: string;
}

function toPascalCase(name: string): string {
  return name.replace(/(^|-)(\w)/g, (_, __, c: string) => c.toUpperCase());
}

export function Lucide({ name, size = 16, color, style, className }: Props) {
  const Icon = (icons as Record<string, React.ComponentType<icons.LucideProps> | undefined>)[
    toPascalCase(name)
  ];
  if (!Icon) {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn(`Lucide: unknown icon name: "${name}"`);
    }
    return (
      <span
        className={className}
        style={{ width: size, height: size, display: 'inline-block', ...style }}
      />
    );
  }
  return (
    <Icon
      size={size}
      color={color}
      strokeWidth={1.75}
      className={className}
      style={style}
    />
  );
}
```

- [ ] **Step A.3.3: typecheck**

```bash
npm run typecheck
```

Expected: passes. (TypeScript may want explicit typing if `icons.LucideProps` isn't exported in some lucide-react versions. If so, replace with `import type { LucideProps } from 'lucide-react'` at the top.)

- [ ] **Step A.3.4: Run the app, click around**

```bash
npm run dev
```

Visually verify icons render across all six screens (sidebar, top bar buttons, today screen, connectors detail panel, meeting catches, capture detail, settings). Expected: every icon renders at least as well as before; no console warnings about unknown icons.

If you see "unknown icon" warnings, check the `name` value at the call site and confirm it's a valid lucide-react export name.

- [ ] **Step A.3.5: Commit**

```bash
git add desktop/
git commit -m "refactor(desktop): migrate Lucide to lucide-react

Replaces hand-rolled createElementNS DOM construction with the proper
React-native package. Treeshakeable, typed, and warns in dev when an
unknown icon name is requested instead of silently rendering nothing."
```

---

## Task A.4: Hoist shared types to src/shared/

**Files:**
- Create: `desktop/src/shared/types.ts`
- Create: `desktop/tsconfig.shared.json`
- Delete: `desktop/src/preload/types.ts`
- Modify: `desktop/tsconfig.json`
- Modify: `desktop/tsconfig.node.json`
- Modify: `desktop/tsconfig.web.json`
- Modify: `desktop/src/main/settings.ts` (import path)
- Modify: `desktop/src/main/dialogs.ts` (no-op: doesn't import types currently — verify)
- Modify: `desktop/src/main/index.ts` (import path)
- Modify: `desktop/src/preload/index.ts` (import path)
- Modify: `desktop/src/renderer/stores/settings.ts` (import path)
- Modify: every other file that imports from `preload/types`

- [ ] **Step A.4.1: Find every importer**

```bash
cd desktop
git grep -l "from '../../preload/types'\|from '../preload/types'\|from './types'" src/
```

Take note of the matches — these are the files whose import paths need updating in this task.

- [ ] **Step A.4.2: Create the shared types module**

Create `desktop/src/shared/types.ts`:

```ts
export type Theme = 'dark' | 'light';
export type Density = 'comfortable' | 'compact';

export interface Settings {
  theme: Theme;
  density: Density;
  vaultPath: string;
}

export interface GbBridge {
  settings: {
    getAll(): Promise<Settings>;
    set<K extends keyof Settings>(
      key: K,
      value: Settings[K],
    ): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  dialogs: {
    pickVaultFolder(): Promise<string | null>;
  };
  shell: {
    openPath(path: string): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  platform: NodeJS.Platform;
}

declare global {
  interface Window {
    gb: GbBridge;
  }
}
```

> Note: the bridge return types for `set` and `openPath` change from raw `Promise<void>`/`Promise<string>` to a result object. Task D.3 implements the validation that uses these. Until then, the main side returns `{ ok: true }` to satisfy the type. We change the type now in Task A.4 to avoid a second pass through every importer later.

- [ ] **Step A.4.3: Create the shared tsconfig**

Create `desktop/tsconfig.shared.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "types": ["node"],
    "outDir": "out/.tsbuildinfo-shared"
  },
  "include": ["src/shared/**/*"]
}
```

- [ ] **Step A.4.4: Wire it into the project root**

Edit `desktop/tsconfig.json`:

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.shared.json" },
    { "path": "./tsconfig.node.json" },
    { "path": "./tsconfig.web.json" }
  ]
}
```

Edit `desktop/tsconfig.node.json` — add the shared reference and include the shared dir:

```json
{
  "compilerOptions": {
    "composite": true,
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "types": ["node"],
    "outDir": "out/.tsbuildinfo-node"
  },
  "references": [{ "path": "./tsconfig.shared.json" }],
  "include": ["src/main/**/*", "src/preload/**/*", "src/shared/**/*", "electron.vite.config.ts"]
}
```

Edit `desktop/tsconfig.web.json` — add the shared reference and include the shared dir:

```json
{
  "compilerOptions": {
    "composite": true,
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "jsx": "react-jsx",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "esModuleInterop": true,
    "skipLibCheck": true,
    "types": ["vite/client"],
    "outDir": "out/.tsbuildinfo-web"
  },
  "references": [{ "path": "./tsconfig.shared.json" }],
  "include": ["src/renderer/**/*", "src/shared/**/*"]
}
```

> The renderer's `tsconfig.web.json` does NOT include `"node"` in `types` — `NodeJS.Platform` reaches the renderer via the shared project's typing because `tsconfig.shared.json` does have `"types": ["node"]`. This is the cleanest way to expose just the platform type without polluting the renderer's globals.

- [ ] **Step A.4.5: Delete the old preload/types.ts**

```bash
rm desktop/src/preload/types.ts
```

- [ ] **Step A.4.6: Update every importer**

For every file matched by Step A.4.1, update the import path from `'../../preload/types'` (or similar) to point at `'../../shared/types'` (or appropriate relative path from each file's location).

Concretely, edit:
- `desktop/src/main/settings.ts` → `from '../shared/types'`
- `desktop/src/main/index.ts` → `from '../shared/types'`
- `desktop/src/preload/index.ts` → `from '../shared/types'`
- `desktop/src/renderer/test/setup.ts` → `from '../../shared/types'`
- `desktop/src/renderer/stores/settings.ts` → `from '../../shared/types'`
- Any other file the grep turned up

- [ ] **Step A.4.7: typecheck**

```bash
cd desktop
npm run typecheck
```

Expected: passes. The renderer can now reference `NodeJS.Platform` through the shared types without `@types/node` being added to its own tsconfig.

- [ ] **Step A.4.8: test + dev sanity**

```bash
npm test
npm run dev   # ~10s, kill
```

Both pass.

- [ ] **Step A.4.9: Commit**

```bash
git add desktop/
git rm desktop/src/preload/types.ts  # if not already staged as a deletion
git commit -m "refactor(desktop): hoist shared types to src/shared/

Settings, GbBridge, Theme, Density, Platform now live in src/shared/types.ts
referenced by main, preload, and renderer via a third tsconfig project. The
renderer-side Platform string-literal duplicate is gone.

Bridge types updated to return result objects for set() and openPath() —
implementation lands in D.3."
```

---

## Task A.5: WebkitAppRegion CSS type augmentation

**Files:**
- Create: `desktop/src/shared/csstype.d.ts`
- Modify: every renderer file that has `as React.CSSProperties` cast to use `WebkitAppRegion`

- [ ] **Step A.5.1: Add the augmentation**

Create `desktop/src/shared/csstype.d.ts`:

```ts
import 'csstype';

declare module 'csstype' {
  interface Properties {
    WebkitAppRegion?: 'drag' | 'no-drag';
  }
}
```

- [ ] **Step A.5.2: Find every cast and remove it**

```bash
cd desktop
git grep -n "as React.CSSProperties" src/renderer/
```

For each match, inspect the style object — if `WebkitAppRegion` was the only reason for the cast, drop the cast and let TS infer.

In practice this is `Sidebar.tsx` (multiple places — top-level aside, the nav, the footer block).

Example before:

```tsx
style={{
  width: 220,
  flexShrink: 0,
  background: 'var(--bg-paper)',
  borderRight: '1px solid var(--hairline)',
  display: 'flex',
  flexDirection: 'column',
  WebkitAppRegion: 'drag',
} as React.CSSProperties}
```

After:

```tsx
style={{
  width: 220,
  flexShrink: 0,
  background: 'var(--bg-paper)',
  borderRight: '1px solid var(--hairline)',
  display: 'flex',
  flexDirection: 'column',
  WebkitAppRegion: 'drag',
}}
```

If a cast served *another* purpose (some other untyped property), leave it.

- [ ] **Step A.5.3: typecheck**

```bash
npm run typecheck
```

Expected: passes. If a cast removal causes an error, that cast was masking a different unrelated issue — fix that issue, don't re-add the cast.

- [ ] **Step A.5.4: Commit**

```bash
git add desktop/
git commit -m "chore(desktop): csstype augmentation for WebkitAppRegion

Removes the as React.CSSProperties casts that were only needed because
WebkitAppRegion isn't in the standard csstype Properties interface."
```

---

## Task A.6: Fix ESLint v9 peer-dep so --legacy-peer-deps isn't needed

**Files:**
- Modify: `desktop/package.json`

- [ ] **Step A.6.1: Identify the offender**

```bash
cd desktop
npm ls eslint --depth=2
npm ls @eslint/js --depth=2
```

Look at the output: which dependency has a `peer` constraint on ESLint that doesn't include v9.39.x? Common suspects: `eslint-plugin-react`, `eslint-plugin-react-hooks`. If a plugin's `peerDependencies` lists `eslint: ^7 || ^8`, that's the conflict.

- [ ] **Step A.6.2: Try upgrading the offender**

Identify the offending plugin and check if a v9-compatible release exists:

```bash
npm view eslint-plugin-react peerDependencies
npm view eslint-plugin-react-hooks peerDependencies
```

If a newer major version of the plugin includes ESLint v9 in its peer range, upgrade:

```bash
npm install --save-dev <plugin>@<latest-version>
```

Repeat for each offender.

- [ ] **Step A.6.3: Reinstall without the legacy flag**

```bash
rm -rf node_modules package-lock.json
npm install
```

Expected: completes without `EBADPEER` errors.

If `npm install` still fails on peer-deps, the upgrade route didn't work. Fall back option: pin `@eslint/js` to a major that satisfies the offender's peer range. Add to `package.json` devDependencies:

```json
"@eslint/js": "9.39.4"
```

(or whatever the offender accepts) and rerun `npm install`. Document the choice in the commit.

- [ ] **Step A.6.4: Verify lint and tests still pass**

```bash
npm run lint
npm test
npm run typecheck
```

All three pass.

- [ ] **Step A.6.5: Commit**

```bash
git add desktop/
git commit -m "chore(desktop): resolve ESLint peer-dep so npm install works without --legacy-peer-deps

[describe what you did — upgrade <plugin> to <version> OR pin <pkg> to <version>]"
```

---

## Task B.1: Extend @theme tokens to cover the design

**Files:**
- Modify: `desktop/src/renderer/styles.css`

- [ ] **Step B.1.1: Audit which inline-style values are common enough to deserve a token**

Run:

```bash
cd desktop
git grep -hE "fontSize: ?[0-9]+" src/renderer/ | sort | uniq -c | sort -rn | head -20
git grep -hE "padding: ?'" src/renderer/ | sort | uniq -c | sort -rn | head -20
git grep -hE "borderRadius: ?[0-9]+" src/renderer/ | sort | uniq -c | sort -rn | head -20
git grep -hE "letterSpacing:" src/renderer/ | sort | uniq -c | sort -rn | head -10
```

Note the common values per category — these become tokens.

- [ ] **Step B.1.2: Extend `@theme` in styles.css**

Open `desktop/src/renderer/styles.css`. Locate the existing `@theme { ... }` block. Extend it with the additional tokens used throughout the app. Replace the existing `@theme` block with:

```css
@theme {
  /* colors */
  --color-paper: var(--bg-paper);
  --color-vellum: var(--bg-vellum);
  --color-fog: var(--bg-fog);
  --color-ink-0: var(--ink-0);
  --color-ink-1: var(--ink-1);
  --color-ink-2: var(--ink-2);
  --color-ink-3: var(--ink-3);
  --color-neon: var(--neon);
  --color-neon-dark: var(--neon-dark);
  --color-neon-mist: var(--neon-mist);
  --color-oxblood: var(--oxblood);
  --color-oxblood-mist: var(--oxblood-mist);
  --color-moss: var(--moss);
  --color-moss-mist: var(--moss-mist);

  /* hairlines (semi-transparent dividers) */
  --color-hairline: var(--hairline);
  --color-hairline-2: var(--hairline-2);
  --color-hairline-3: var(--hairline-3);

  /* fonts */
  --font-display: 'Google Sans Flex', ui-sans-serif, system-ui, sans-serif;
  --font-body: 'Google Sans Flex', ui-sans-serif, system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;

  /* font sizes — design uses these specific values */
  --text-9: 9px;
  --text-10: 10px;
  --text-11: 11px;
  --text-12: 12px;
  --text-13: 13px;
  --text-14: 14px;
  --text-16: 16px;
  --text-18: 18px;
  --text-20: 20px;
  --text-22: 22px;
  --text-26: 26px;
  --text-28: 28px;
  --text-32: 32px;
  --text-38: 38px;
  --text-72: 72px;

  /* tracking (letter-spacing) */
  --tracking-tightest: -0.035em;
  --tracking-tighter: -0.03em;
  --tracking-tight-x: -0.025em;
  --tracking-tight-xx: -0.02em;
  --tracking-eyebrow: 0.12em;
  --tracking-eyebrow-loose: 0.14em;

  /* radii */
  --radius-xs: 2px;
  --radius-sm: 4px;
  --radius-r6: 6px;
  --radius-md: 8px;
  --radius-r10: 10px;
  --radius-lg: 12px;
  --radius-pill: 999px;

  /* shadows */
  --shadow-card: 0 2px 4px rgba(0, 0, 0, 0.3), 0 12px 24px rgba(0, 0, 0, 0.45);
  --shadow-float: 0 16px 40px rgba(0, 0, 0, 0.55), 0 2px 6px rgba(0, 0, 0, 0.4);
  --shadow-glow-neon: 0 0 0 1px rgba(197, 255, 61, 0.35), 0 0 24px rgba(197, 255, 61, 0.25);
}
```

- [ ] **Step B.1.3: Verify Tailwind picks up the new tokens**

```bash
cd desktop
npm run dev
```

In DevTools, inspect any element. Try adding a class like `text-13` or `rounded-r6` to App.tsx temporarily and confirm the resulting computed style picks up the right value. Revert the temporary class after.

- [ ] **Step B.1.4: typecheck + lint + test**

```bash
npm run typecheck
npm run lint
npm test
```

All pass. (The CSS change shouldn't affect TS or tests.)

- [ ] **Step B.1.5: Commit**

```bash
git add desktop/src/renderer/styles.css
git commit -m "feat(desktop): extend @theme tokens to cover design's full scale

Adds all font sizes, tracking values, radii, shadows, and hairline colors
that the inline styles use. Subsequent B.2 tasks migrate component-by-
component to consume these via Tailwind utilities."
```

---

## Task B.2.a: Migrate primitives + chrome to Tailwind

**Files:**
- Modify: `desktop/src/renderer/components/Eyebrow.tsx`
- Modify: `desktop/src/renderer/components/Pill.tsx`
- Modify: `desktop/src/renderer/components/Toggle.tsx`
- Modify: `desktop/src/renderer/components/Catch.tsx`
- Modify: `desktop/src/renderer/components/Ghost.tsx`
- Modify: `desktop/src/renderer/components/Btn.tsx`
- Modify: `desktop/src/renderer/components/Lucide.tsx`
- Modify: `desktop/src/renderer/components/Panel.tsx`
- Modify: `desktop/src/renderer/components/TopBar.tsx`
- Modify: `desktop/src/renderer/components/StatusBar.tsx`
- Modify: `desktop/src/renderer/components/WindowChrome.tsx`
- Modify: `desktop/src/renderer/components/Toaster.tsx`

For each file: replace inline `style={{}}` objects with `className=` strings. Keep `style={{}}` only for genuinely-dynamic values (per-render computed colors, sizes, animation states).

- [ ] **Step B.2.a.1: Migrate Eyebrow.tsx**

Replace `desktop/src/renderer/components/Eyebrow.tsx` with:

```tsx
interface Props {
  children: React.ReactNode;
  className?: string;
}

export function Eyebrow({ children, className = '' }: Props) {
  return (
    <div
      className={`font-mono text-10 font-medium uppercase tracking-eyebrow-loose text-ink-2 ${className}`}
    >
      {children}
    </div>
  );
}
```

> Note: prop signature changes from `style?` to `className?`. Callers that pass `style={{ marginTop: 16 }}` etc. need to migrate to `className="mt-4"`. Track these as you encounter them in B.2.c–B.2.f.

- [ ] **Step B.2.a.2: Migrate Pill.tsx**

Pill keeps the runtime-selected palette logic (the color depends on `tone`), but uses Tailwind classes for the static parts:

```tsx
type Tone = 'neon' | 'moss' | 'oxblood' | 'fog' | 'outline';

interface Props {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
}

const toneClasses: Record<Tone, string> = {
  neon: 'bg-neon/15 text-neon',
  moss: 'bg-moss/20 text-[#A2C795]',
  oxblood: 'bg-oxblood/15 text-[#FF8A7C]',
  fog: 'bg-fog text-ink-1',
  outline: 'bg-transparent text-ink-2 border border-hairline-2',
};

export function Pill({ tone = 'neon', children, className = '' }: Props) {
  return (
    <span
      className={`inline-flex items-center gap-[5px] whitespace-nowrap rounded-sm px-[7px] py-[2px] font-mono text-10 font-medium lowercase ${toneClasses[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
```

- [ ] **Step B.2.a.3: Migrate Toggle.tsx**

```tsx
import { useState } from 'react';

interface Props {
  label?: string;
  on: boolean;
  onChange?: (next: boolean) => void;
}

export function Toggle({ label, on: initial, onChange }: Props) {
  const [on, setOn] = useState(initial);
  const toggle = () => {
    const next = !on;
    setOn(next);
    onChange?.(next);
  };
  return (
    <label className="flex cursor-pointer items-center gap-[10px] text-12 text-ink-1">
      <button
        type="button"
        onClick={toggle}
        className={`relative h-4 w-7 flex-shrink-0 cursor-pointer rounded-pill border border-hairline-2 transition-colors duration-[120ms] ${on ? 'bg-neon' : 'bg-fog'}`}
        aria-pressed={on}
      >
        <span
          className={`absolute top-px h-3 w-3 rounded-full transition-[left] duration-[160ms] ease-[cubic-bezier(.2,.8,.2,1)] ${on ? 'left-[13px] bg-paper' : 'left-px bg-ink-2'}`}
        />
      </button>
      {label && <span>{label}</span>}
    </label>
  );
}
```

> The thumb's "off" state uses `bg-ink-2` and "on" state uses `bg-paper` (`#0E0F12` in dark mode, light bone in light mode). This is intentional: the on-state thumb stays dark on neon. Note the small `aria-pressed` addition — bonus a11y.

> Note: the Toggle component should also become *controlled*. Task C.1 expands settings keys; in this task we keep the existing internal state model (initial value as prop, internal `useState`) so the migration is purely styling. C.1 can convert to fully controlled.

- [ ] **Step B.2.a.4: Migrate Catch.tsx**

```tsx
import { Lucide } from './Lucide';

interface Props {
  icon: string;
  text: string;
}

export function Catch({ icon, text }: Props) {
  return (
    <div className="flex items-start gap-2 rounded-sm px-[6px] py-2 text-12 leading-[1.4] text-ink-0">
      <Lucide name={icon} size={12} color="var(--neon)" className="mt-[3px]" />
      <span>{text}</span>
    </div>
  );
}
```

- [ ] **Step B.2.a.5: Migrate Ghost.tsx**

Ghost.tsx is mostly an SVG. Keep the SVG as is — only the wrapping `style` for animation / sizing migrates:

```tsx
interface Props {
  size?: number;
  color?: string;
  floating?: boolean;
  className?: string;
}

export function Ghost({ size = 22, color = 'var(--neon)', floating = false, className = '' }: Props) {
  return (
    <svg
      viewBox="0 0 100 110"
      width={size}
      height={size * 1.1}
      aria-hidden="true"
      className={`flex-shrink-0 ${floating ? 'gb-floating' : ''} ${className}`}
    >
      <path
        d="M 50 6 C 24 6, 10 24, 10 50 L 10 94 Q 17 102, 24 95 Q 31 88, 38 95 Q 44 102, 50 95 Q 56 88, 62 95 Q 69 102, 76 95 Q 83 88, 90 94 L 90 50 C 90 24, 76 6, 50 6 Z"
        fill={color}
      />
      <circle cx="38" cy="48" r="3.2" fill="var(--bg-paper)" />
      <circle cx="62" cy="48" r="3.2" fill="var(--bg-paper)" />
    </svg>
  );
}
```

> Width/height go to attributes (proper SVG), not inline style. The `gb-floating` class already exists in styles.css.

- [ ] **Step B.2.a.6: Migrate Btn.tsx**

Replace `desktop/src/renderer/components/Btn.tsx` with:

```tsx
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'record';
type Size = 'sm' | 'md' | 'lg';

interface Props {
  variant?: Variant;
  size?: Size;
  icon?: React.ReactNode;
  iconRight?: React.ReactNode;
  children?: React.ReactNode;
  onClick?: () => void;
  className?: string;
  disabled?: boolean;
  type?: 'button' | 'submit';
  ariaLabel?: string;
}

const sizeClasses: Record<Size, string> = {
  sm: 'px-[10px] py-[6px] text-12 gap-[6px]',
  md: 'px-[14px] py-2 text-13 gap-[7px]',
  lg: 'px-[18px] py-[11px] text-14 gap-2',
};

const variantClasses: Record<Variant, string> = {
  primary:
    'bg-neon text-[#0E0F12] border border-transparent hover:bg-neon-dark',
  secondary:
    'bg-vellum text-ink-0 border border-hairline-2 hover:bg-fog',
  ghost: 'bg-transparent text-ink-1 border border-transparent hover:bg-vellum',
  danger:
    'bg-oxblood/10 text-oxblood border border-oxblood/30 hover:bg-oxblood/20',
  record: 'bg-oxblood text-[#0E0F12] border border-transparent hover:bg-[#E8584C]',
};

export function Btn({
  variant = 'primary',
  size = 'md',
  icon,
  iconRight,
  children,
  onClick,
  className = '',
  disabled,
  type = 'button',
  ariaLabel,
}: Props) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      aria-label={ariaLabel}
      className={`inline-flex items-center justify-center whitespace-nowrap rounded-r6 font-body font-medium transition-all duration-[120ms] ease-[cubic-bezier(.2,.8,.2,1)] disabled:cursor-not-allowed disabled:opacity-50 ${sizeClasses[size]} ${variantClasses[variant]} ${className}`}
    >
      {icon}
      {children}
      {iconRight}
    </button>
  );
}
```

> The hover state moves entirely from `useState` + JS-side branching to CSS `:hover` via Tailwind. Simpler, cheaper, more accessible (CSS pseudo-class fires on focus too if you add `focus:` variants in a follow-up).

> The `#0E0F12` literal stays in primary/record because it's an intentionally fixed dark text color on bright backgrounds; light-mode flipping it would reduce contrast.

- [ ] **Step B.2.a.7: Migrate Lucide.tsx**

After A.3 the file is already a thin lucide-react wrapper. Confirm it has no inline `style={{}}` objects beyond the optional `style` prop pass-through. Audit the empty-fallback span and convert to className:

```tsx
import * as icons from 'lucide-react';

interface Props {
  name: string;
  size?: number;
  color?: string;
  style?: React.CSSProperties;
  className?: string;
}

function toPascalCase(name: string): string {
  return name.replace(/(^|-)(\w)/g, (_, __, c: string) => c.toUpperCase());
}

export function Lucide({ name, size = 16, color, style, className = '' }: Props) {
  const Icon = (icons as Record<string, React.ComponentType<icons.LucideProps> | undefined>)[
    toPascalCase(name)
  ];
  if (!Icon) {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn(`Lucide: unknown icon name: "${name}"`);
    }
    return (
      <span
        className={`inline-block flex-shrink-0 ${className}`}
        style={{ width: size, height: size, ...style }}
      />
    );
  }
  return (
    <Icon
      size={size}
      color={color}
      strokeWidth={1.75}
      className={`flex-shrink-0 ${className}`}
      style={style}
    />
  );
}
```

> The `width`/`height`/`color` stay in inline style/props because they're per-call dynamic values — exactly the case where inline style is correct.

- [ ] **Step B.2.a.8: Migrate Panel.tsx**

```tsx
interface Props {
  title: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

export function Panel({ title, subtitle, action, children, className = '' }: Props) {
  return (
    <section
      className={`rounded-r10 border border-hairline bg-vellum ${className}`}
    >
      <header className="flex items-center gap-[10px] border-b border-hairline px-4 py-3">
        <div className="flex flex-1 items-baseline gap-[10px]">
          <h3 className="m-0 text-13 font-medium text-ink-0">{title}</h3>
          {subtitle && (
            <span className="font-mono text-10 text-ink-2">{subtitle}</span>
          )}
        </div>
        {action}
      </header>
      <div className="flex flex-col gap-1 p-3">{children}</div>
    </section>
  );
}
```

- [ ] **Step B.2.a.9: Migrate TopBar.tsx**

```tsx
interface Props {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}

export function TopBar({ title, subtitle, right }: Props) {
  return (
    <div className="gb-topbar flex h-14 flex-shrink-0 items-center gap-4 border-b border-hairline bg-paper px-6">
      <div className="flex flex-col gap-[2px] leading-[1.15]">
        <h1 className="m-0 font-display text-20 font-semibold tracking-tight-xx text-ink-0">
          {title}
        </h1>
        {subtitle && (
          <span className="font-mono text-10 uppercase tracking-eyebrow text-ink-2">
            {subtitle}
          </span>
        )}
      </div>
      <div className="flex-1" />
      {right}
    </div>
  );
}
```

> The `gb-topbar` class is added so density CSS in C.2 can target it.

- [ ] **Step B.2.a.10: Migrate StatusBar.tsx**

```tsx
import { Lucide } from './Lucide';
import { useMeeting } from '../stores/meeting';

export function StatusBar() {
  const phase = useMeeting((s) => s.phase);
  return (
    <footer className="gb-statusbar flex h-[26px] flex-shrink-0 items-center gap-4 border-t border-hairline bg-vellum px-[14px] font-mono text-10 lowercase text-ink-2">
      <span className="inline-flex items-center gap-[5px]">
        <span className="h-[6px] w-[6px] rounded-full bg-neon" />
        6 connectors live
      </span>
      <span>·</span>
      <span>2,489 indexed</span>
      <span>·</span>
      <span>last sync 1m ago</span>
      {phase === 'recording' && (
        <>
          <span>·</span>
          <span className="inline-flex items-center gap-[5px] text-oxblood">
            <span
              className="h-[6px] w-[6px] rounded-full bg-oxblood"
              style={{ animation: 'gb-pulse 1.4s ease-out infinite' }}
            />
            recording
          </span>
        </>
      )}
      <div className="flex-1" />
      <span className="inline-flex items-center gap-[5px]">
        <Lucide name="cpu" size={9} /> 0.4% cpu
      </span>
      <span>·</span>
      <span>vault encrypted</span>
    </footer>
  );
}
```

> The `gb-pulse` animation stays as inline style because Tailwind doesn't have a utility for `animation` shorthand. Could add as a custom utility later; not worth it for one usage.

- [ ] **Step B.2.a.11: Migrate WindowChrome.tsx**

```tsx
interface Props {
  children: React.ReactNode;
}

export function WindowChrome({ children }: Props) {
  return (
    <div className="relative flex h-full w-full flex-col bg-paper">{children}</div>
  );
}
```

- [ ] **Step B.2.a.12: Migrate Toaster.tsx**

```tsx
import { useToasts } from '../stores/toast';

export function Toaster() {
  const toasts = useToasts((s) => s.toasts);
  return (
    <div className="pointer-events-none fixed bottom-10 right-5 z-[1000] flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="rounded-md border border-hairline-2 bg-vellum px-[14px] py-[10px] font-mono text-12 text-ink-0 shadow-card"
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
```

> Task E.1 expands this with kind-aware styling.

- [ ] **Step B.2.a.13: Verify**

```bash
cd desktop
npm run typecheck
npm run lint
npm test
npm run dev    # ~10s, click around all six screens
```

Expected: all pass; visual fidelity preserved.

If any screen visually breaks (e.g. a row's spacing is off), check whether a caller is passing `style={{}}` to a component whose prop signature changed. Migrate the caller's prop to `className`.

- [ ] **Step B.2.a.14: Commit**

```bash
git add desktop/src/renderer/components/
git commit -m "refactor(desktop): migrate primitives and chrome to Tailwind

12 files: Eyebrow, Pill, Toggle, Catch, Ghost, Btn, Lucide, Panel, TopBar,
StatusBar, WindowChrome, Toaster. Inline style objects replaced with
Tailwind utility classes. Btn hover state moves from useState to :hover
pseudo-class. Eyebrow/Panel/etc. prop signatures change from style? to
className?; per-screen migration in subsequent tasks."
```

---

## Task B.2.b: Migrate Sidebar to Tailwind

**Files:**
- Modify: `desktop/src/renderer/components/Sidebar.tsx`

Sidebar gets its own task because: it has the drag-region behavior, the active-state pseudo-bar overlay, the conditional traffic-light spacer, and complex nested NavRow/VaultRow components.

- [ ] **Step B.2.b.1: Migrate Sidebar.tsx**

Replace `desktop/src/renderer/components/Sidebar.tsx` with:

```tsx
import { Lucide } from './Lucide';
import { Ghost } from './Ghost';
import { Eyebrow } from './Eyebrow';
import { useNavigation, type ScreenId } from '../stores/navigation';
import { useMeeting } from '../stores/meeting';
import { isMac } from '../lib/platform';

const NAV_ITEMS: Array<{ id: ScreenId; icon: string; label: string }> = [
  { id: 'today', icon: 'sparkles', label: 'today' },
  { id: 'connectors', icon: 'plug', label: 'connectors' },
  { id: 'meetings', icon: 'mic', label: 'meetings' },
  { id: 'capture', icon: 'inbox', label: 'capture' },
  { id: 'vault', icon: 'book-open', label: 'vault' },
  { id: 'settings', icon: 'settings', label: 'settings' },
];

const VAULT_FOLDERS = [
  { icon: 'folder', label: 'Daily', count: 284 },
  { icon: 'folder', label: 'Meetings', count: 47 },
  { icon: 'folder', label: 'People', count: 91 },
  { icon: 'folder', label: 'Projects', count: 23 },
  { icon: 'hash', label: '#followup', count: 8 },
];

function RecordingDot() {
  return (
    <span
      className="h-2 w-2 rounded-full bg-oxblood"
      style={{ animation: 'gb-pulse 1.4s ease-out infinite' }}
    />
  );
}

export function Sidebar() {
  const { active, setActive } = useNavigation();
  const phase = useMeeting((s) => s.phase);
  return (
    <aside
      className="flex w-[220px] flex-shrink-0 flex-col border-r border-hairline bg-paper"
      style={{ WebkitAppRegion: 'drag' }}
    >
      {isMac && <div className="h-9 flex-shrink-0" />}

      <div className="flex items-center gap-[10px] px-[14px] pb-2 pt-[14px]">
        <Ghost size={20} floating />
        <div className="flex flex-col leading-[1.1]">
          <span className="font-display text-16 font-semibold tracking-tight-xx text-ink-0">
            ghostbrain
          </span>
          <span className="font-mono text-9 uppercase tracking-eyebrow text-ink-2">
            v 0.1.0 · haunting
          </span>
        </div>
      </div>

      <nav
        className="gb-sidenav flex-1 overflow-y-auto px-2 py-3"
        style={{ WebkitAppRegion: 'no-drag' }}
      >
        <Eyebrow className="px-[10px] py-[6px]">workspace</Eyebrow>
        {NAV_ITEMS.map((item) => (
          <NavRow
            key={item.id}
            item={item}
            active={active === item.id}
            onClick={() => setActive(item.id)}
            badge={
              item.id === 'meetings' && phase === 'recording' ? (
                <RecordingDot />
              ) : item.id === 'capture' ? (
                '12'
              ) : null
            }
          />
        ))}
        <Eyebrow className="mt-4 px-[10px] py-[6px]">vault</Eyebrow>
        {VAULT_FOLDERS.map((f) => (
          <VaultRow key={f.label} {...f} />
        ))}
      </nav>

      <div
        className="flex items-center gap-2 border-t border-hairline px-[14px] py-[10px]"
        style={{ WebkitAppRegion: 'no-drag' }}
      >
        <div className="flex h-[26px] w-[26px] flex-shrink-0 items-center justify-center rounded-sm bg-fog">
          <Lucide name="hard-drive" size={13} color="var(--ink-1)" />
        </div>
        <div className="min-w-0 flex-1 leading-[1.2]">
          <div className="overflow-hidden text-ellipsis whitespace-nowrap text-11 font-medium text-ink-0">
            ~/ghostbrain/vault
          </div>
          <div className="font-mono text-9 text-ink-2">local · synced</div>
        </div>
      </div>
    </aside>
  );
}

function NavRow({
  item,
  active,
  onClick,
  badge,
}: {
  item: { id: ScreenId; icon: string; label: string };
  active: boolean;
  onClick: () => void;
  badge: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`gb-navrow relative flex w-full items-center gap-[10px] rounded-r6 px-[10px] py-[7px] text-left text-13 transition-colors duration-[120ms] ${
        active ? 'bg-neon/12 font-medium text-ink-0' : 'font-normal text-ink-1 hover:bg-vellum'
      }`}
    >
      {active && (
        <span className="absolute -left-2 bottom-[6px] top-[6px] w-[2px] rounded-sm bg-neon" />
      )}
      <Lucide name={item.icon} size={15} color={active ? 'var(--neon)' : 'var(--ink-2)'} />
      <span className="flex-1">{item.label}</span>
      {badge &&
        (typeof badge === 'string' ? (
          <span className="font-mono text-10 text-ink-2">{badge}</span>
        ) : (
          badge
        ))}
    </button>
  );
}

function VaultRow({ icon, label, count }: { icon: string; label: string; count: number }) {
  return (
    <button
      type="button"
      className="flex w-full items-center gap-2 rounded-sm px-[10px] py-[5px] text-left text-12 text-ink-1 transition-colors duration-[120ms] hover:bg-vellum"
    >
      <Lucide name={icon} size={12} color="var(--ink-3)" />
      <span className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap">{label}</span>
      <span className="font-mono text-9 text-ink-3">{count}</span>
    </button>
  );
}
```

> Two improvements baked in:
> - `NavRow` and `VaultRow` change from `<div onClick>` to `<button>` — proper a11y (keyboard, screen readers).
> - The `useState` hover state is gone; CSS `:hover` handles it.
>
> The drag region inline style stays because it's the one place a runtime DOM property has no Tailwind utility.

- [ ] **Step B.2.b.2: Verify**

```bash
cd desktop
npm run typecheck && npm run lint && npm test
npm run dev   # click between all 6 nav rows, confirm active state, hover states, recording dot
```

- [ ] **Step B.2.b.3: Commit**

```bash
git add desktop/src/renderer/components/Sidebar.tsx
git commit -m "refactor(desktop): migrate Sidebar to Tailwind, NavRow/VaultRow as real buttons

Active-state indicator stays absolute-positioned; hover states move to CSS :hover;
NavRow and VaultRow become <button>s instead of <div onClick>."
```

---

## Task B.2.c: Migrate Today screen to Tailwind

**Files:**
- Modify: `desktop/src/renderer/screens/today.tsx`

Today.tsx is the largest screen (~250 lines). Migration is mostly mechanical: replace `style={{}}` with `className="..."` per element.

- [ ] **Step B.2.c.1: Migrate today.tsx**

Open `desktop/src/renderer/screens/today.tsx`. For every element, translate inline styles to Tailwind classes. The patterns repeat:

| Inline | Tailwind |
|---|---|
| `display: 'flex', gap: 8` | `flex gap-2` |
| `padding: '24px 32px'` | `px-8 py-6` |
| `display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 28` | `grid grid-cols-[1.4fr_1fr] gap-7` |
| `border: '1px solid var(--hairline)'` | `border border-hairline` |
| `borderRadius: 12, padding: 28` | `rounded-lg p-7` |
| `fontFamily: 'var(--font-display)', fontSize: 38, fontWeight: 600` | `font-display text-38 font-semibold` |
| `color: 'var(--ink-2)'` | `text-ink-2` |
| `background: 'var(--bg-vellum)'` | `bg-vellum` |
| `letterSpacing: '-0.035em'` | `tracking-tightest` |
| `lineHeight: 1.05` | `leading-[1.05]` |

Keep `style={{}}` for these specific cases:
- Radial gradients with computed positions: `style={{ background: 'radial-gradient(circle, ...)' }}`
- The hero greeting's noise overlay (already a class `gb-noise`)
- Per-row dynamic colors: `style={{ background: tone === 'neon' ? ... }}` — convert these to conditional classes when the branch count is small (≤3); leave inline if dynamic
- Per-stat tone-driven color: in the `Stat` sub-component the `color: tone === 'neon' ? 'var(--neon)' : 'var(--ink-0)'` becomes a conditional className

Replace the `Eyebrow` callers — they previously passed `style={{ marginBottom: 8 }}`; now pass `className="mb-2"`.

> Because the file is large, do this in chunks: hero block first, then agenda+activity row, then connector pulse strip, then bottom row, then sub-components. After each chunk run `npm run dev` and visually compare to the previous build.

- [ ] **Step B.2.c.2: Verify**

```bash
cd desktop
npm run typecheck && npm run lint && npm test
npm run dev   # navigate to Today; compare side-by-side to previous-build screenshot if needed
```

If anything visually drifted, the Tailwind class for that property is missing or wrong. Check the rendered computed style in DevTools.

- [ ] **Step B.2.c.3: Commit**

```bash
git add desktop/src/renderer/screens/today.tsx
git commit -m "refactor(desktop): migrate Today screen to Tailwind"
```

---

## Task B.2.d: Migrate Connectors screen to Tailwind

**Files:**
- Modify: `desktop/src/renderer/screens/connectors.tsx`

- [ ] **Step B.2.d.1: Migrate connectors.tsx**

Apply the same pattern as B.2.c. Specific notes for this screen:

- The grid-template-columns we added in the alignment fix (`32px minmax(0, 1fr) 100px 120px 120px 90px`) doesn't have a clean Tailwind utility. Use `style={{ gridTemplateColumns: '32px minmax(0, 1fr) 100px 120px 120px 90px' }}` and class `grid gap-3` for the rest.
- Filter chip styling: each chip changes appearance based on `filter === f`. Conditional className:
  ```tsx
  className={`cursor-pointer rounded-sm border px-[10px] py-1 font-mono text-11 ${
    filter === f
      ? 'border-neon/30 bg-neon/15 text-neon'
      : 'border-hairline-2 bg-transparent text-ink-1'
  }`}
  ```
- `ConnectorRow`'s opacity-on-off branch: use `${c.state === 'off' ? 'opacity-65' : ''}` (Tailwind has `opacity-65` if you've extended; if not, use `opacity-[0.65]`).
- The `<img>` `filter: grayscale(1)` stays as inline style since `filter:` shorthand doesn't have a clean Tailwind utility for grayscale-fixed-amount with a conditional.

- [ ] **Step B.2.d.2: Verify**

```bash
cd desktop
npm run typecheck && npm run lint && npm test
npm run dev   # navigate to Connectors; click filter chips, click rows, verify detail panel updates
```

- [ ] **Step B.2.d.3: Commit**

```bash
git add desktop/src/renderer/screens/connectors.tsx
git commit -m "refactor(desktop): migrate Connectors screen to Tailwind"
```

---

## Task B.2.e: Migrate Meetings screen to Tailwind

**Files:**
- Modify: `desktop/src/renderer/screens/meetings.tsx`

- [ ] **Step B.2.e.1: Migrate meetings.tsx**

Largest screen file. Apply the same pattern. Specific notes:

- The live banner gradient `background: 'linear-gradient(90deg, rgba(255,107,90,0.18) 0%, rgba(255,107,90,0.04) 100%)'` stays as inline style (no clean Tailwind utility for arbitrary gradients).
- Waveform bars: `width: ${h * 100}%` is per-bar dynamic — stays inline. Keyframe `gb-wave` stays inline.
- Transcript live cursor: small blink `<span>` keeps inline style (`animation: 'gb-blink 1s steps(2) infinite'`).
- Speaker airtime bars: `width: ${SPEAKER_AIRTIME[i]}%` stays inline. Color from PARTICIPANTS data stays inline (`background: p.color`).
- The pulse animation on the live recording dot stays inline.
- Action checkbox: the empty checkbox `<div>` becomes a real disabled `<input type="checkbox" />` for a11y. Style it minimally.

For action items, replace:
```tsx
<div style={{ width: 12, height: 12, borderRadius: 3, border: '1.5px solid var(--ink-3)', flexShrink: 0, marginTop: 3 }}></div>
```

With:
```tsx
<input
  type="checkbox"
  disabled
  className="mt-[3px] h-3 w-3 flex-shrink-0 rounded-sm border-[1.5px] border-ink-3 bg-transparent"
/>
```

- [ ] **Step B.2.e.2: Verify**

```bash
cd desktop
npm run typecheck && npm run lint && npm test
npm run dev   # navigate to Meetings; cycle through pre/recording/post; verify timer ticks; verify transcript renders
```

- [ ] **Step B.2.e.3: Commit**

```bash
git add desktop/src/renderer/screens/meetings.tsx
git commit -m "refactor(desktop): migrate Meetings screen to Tailwind"
```

---

## Task B.2.f: Migrate Capture, Vault, Settings to Tailwind

**Files:**
- Modify: `desktop/src/renderer/screens/capture.tsx`
- Modify: `desktop/src/renderer/screens/vault.tsx`
- Modify: `desktop/src/renderer/screens/settings.tsx`

These three are smaller; group them.

- [ ] **Step B.2.f.1: Migrate capture.tsx**

Same pattern as connectors. The chip styling helper `chipStyle(active: boolean)` becomes a `chipClass(active: boolean): string` returning a className string:

```ts
function chipClass(active: boolean): string {
  return `cursor-pointer rounded-sm border px-[10px] py-1 font-mono text-11 ${
    active
      ? 'border-neon/30 bg-neon/15 text-neon'
      : 'border-hairline-2 bg-transparent text-ink-1'
  }`;
}
```

The `CaptureRow` becomes a real `<button>` (a11y). Same for the row in `today.tsx` if not already done.

- [ ] **Step B.2.f.2: Migrate vault.tsx**

Small file. Straightforward pattern.

- [ ] **Step B.2.f.3: Migrate settings.tsx**

Largest of the three. Specific notes:

- `selectStyle` constant becomes a `selectClass = '...'` constant string used in `className` instead of `style`.
- `SectionRow` becomes a real `<button>` (a11y).
- The `Segmented` component's option buttons should also be real `<button>`s; mostly already are. Add `aria-pressed` for selected state.
- The Account section's "T" avatar: keep `color: '#0E0F12'` literal but note it's intentional contrast on neon — add a one-line comment.

- [ ] **Step B.2.f.4: Verify**

```bash
cd desktop
npm run typecheck && npm run lint && npm test
npm run dev   # navigate to each: Capture, Vault, Settings; click around all sections
```

- [ ] **Step B.2.f.5: Commit**

```bash
git add desktop/src/renderer/screens/
git commit -m "refactor(desktop): migrate Capture, Vault, Settings to Tailwind"
```

---

## Task B.3: Hex literal audit

**Files:**
- Possibly modify: any renderer file with anonymous hex literals

- [ ] **Step B.3.1: Find every hex literal**

```bash
cd desktop
git grep -nE "#[0-9A-Fa-f]{3,8}" src/renderer/ | grep -v "0E0F12.*intentional\|FF8A7C\|A2C795"
```

(Adjust the grep-v list as needed; the goal is to filter out already-commented intentional fixed colors.)

- [ ] **Step B.3.2: For each match, decide**

- **Token-equivalent**: replace with the Tailwind class for the existing token. E.g. `#C5FF3D` → `text-neon` or `bg-neon`.
- **Already-tokenized but written as hex by mistake**: same — replace.
- **Intentional fixed color** (e.g. dark text on always-bright background): keep, add a one-line `// intentional fixed color: <reason>` comment above the line.
- **Duplicate of an existing color**: replace with the canonical token.

- [ ] **Step B.3.3: typecheck + lint + test**

```bash
npm run typecheck
npm run lint
npm test
```

All pass.

- [ ] **Step B.3.4: Commit**

```bash
git add desktop/src/renderer/
git commit -m "chore(desktop): audit and tokenize anonymous hex literals

Every hex literal in the renderer is now either a tokenized color or
explicitly commented as an intentional fixed color."
```

---

## Task B.4: Light-mode walkthrough

**Files:**
- Possibly modify: any renderer file with theme-broken styling

- [ ] **Step B.4.1: Run the app in light mode**

```bash
cd desktop
npm run dev
```

In Settings → Display, switch theme to light. Walk through every screen:

1. Today
2. Connectors (all 7 connectors selected, each filter chip)
3. Meetings (cycle through pre / recording / post)
4. Capture (different items selected, different filters)
5. Vault
6. Settings (every section)

Note every visual break: invisible text, low-contrast borders, missing backgrounds, wrong-colored pills, etc.

- [ ] **Step B.4.2: Fix each finding**

For each issue:
- If a hex literal is the cause: replace with a token.
- If a token's light-mode value in `colors_and_type.css` is wrong: adjust the value.
- If a Pill or Btn variant uses a hard-coded color that worked in dark but fails in light: extend the variant to flip with theme (typically by using a CSS var that has different values in light vs dark).

- [ ] **Step B.4.3: Re-walk every screen in light mode**

Confirm every issue is fixed. Then switch to dark mode and re-walk to make sure no regressions.

- [ ] **Step B.4.4: typecheck + lint + test**

All pass.

- [ ] **Step B.4.5: Commit**

```bash
git add desktop/
git commit -m "fix(desktop): light-mode pass across all six screens

Specific fixes: [list each fix in the body — e.g. 'Btn primary text now
uses var(--bg-paper) so it flips correctly in light mode']."
```

---

## Task C.1: Extend Settings schema and wire toggles

**Files:**
- Modify: `desktop/src/shared/types.ts`
- Modify: `desktop/src/main/settings.ts`
- Modify: `desktop/src/renderer/stores/settings.ts`
- Modify: `desktop/src/renderer/components/Toggle.tsx`
- Modify: `desktop/src/renderer/screens/settings.tsx`

- [ ] **Step C.1.1: Extend the Settings interface**

Edit `desktop/src/shared/types.ts`. Replace the `Settings` interface with:

```ts
export type Theme = 'dark' | 'light';
export type Density = 'comfortable' | 'compact';
export type LlmProvider = 'local' | 'anthropic' | 'openai';
export type AudioRetention = '30d' | '7d' | 'immediate' | 'forever';
export type TranscriptModel = 'whisper-large-v3' | 'whisper-medium';
export type FolderStructure = 'by-source' | 'by-date' | 'by-person';

export interface Settings {
  theme: Theme;
  density: Density;
  vaultPath: string;

  dailyNoteEnabled: boolean;
  markdownFrontmatter: boolean;
  autoLinkMentions: boolean;

  cloudSync: boolean;
  e2eEncryption: boolean;
  telemetry: boolean;
  llmProvider: LlmProvider;

  autoRecordFromCalendar: boolean;
  diarizeSpeakers: boolean;
  extractActionItems: boolean;
  audioRetention: AudioRetention;
  transcriptModel: TranscriptModel;

  folderStructure: FolderStructure;
}
```

- [ ] **Step C.1.2: Update the main-side defaults**

Edit `desktop/src/main/settings.ts`. Replace the `defaults` constant with:

```ts
const defaults: Settings = {
  theme: 'dark',
  density: 'comfortable',
  vaultPath: join(homedir(), 'ghostbrain', 'vault'),

  dailyNoteEnabled: true,
  markdownFrontmatter: true,
  autoLinkMentions: true,

  cloudSync: false,
  e2eEncryption: true,
  telemetry: false,
  llmProvider: 'local',

  autoRecordFromCalendar: true,
  diarizeSpeakers: true,
  extractActionItems: true,
  audioRetention: '30d',
  transcriptModel: 'whisper-large-v3',

  folderStructure: 'by-source',
};
```

The merge-with-defaults logic in `read()` already handles the missing-key case for users with an existing config.json — they get the new defaults persisted on first write.

- [ ] **Step C.1.3: Update the renderer settings store**

Edit `desktop/src/renderer/stores/settings.ts`. The state machine already extends `Settings`, so the only change is updating the placeholder defaults to match the schema:

```ts
import { create } from 'zustand';
import type { Settings } from '../../shared/types';

interface SettingsState extends Settings {
  ready: boolean;
  hydrate: () => Promise<void>;
  set: <K extends keyof Settings>(
    key: K,
    value: Settings[K],
  ) => Promise<{ ok: true } | { ok: false; error: string }>;
}

export const useSettings = create<SettingsState>((set) => ({
  // placeholder defaults — overwritten on hydrate()
  theme: 'dark',
  density: 'comfortable',
  vaultPath: '',
  dailyNoteEnabled: true,
  markdownFrontmatter: true,
  autoLinkMentions: true,
  cloudSync: false,
  e2eEncryption: true,
  telemetry: false,
  llmProvider: 'local',
  autoRecordFromCalendar: true,
  diarizeSpeakers: true,
  extractActionItems: true,
  audioRetention: '30d',
  transcriptModel: 'whisper-large-v3',
  folderStructure: 'by-source',
  ready: false,
  hydrate: async () => {
    const all = await window.gb.settings.getAll();
    set({ ...all, ready: true });
  },
  set: async (key, value) => {
    const result = await window.gb.settings.set(key, value);
    if (result.ok) {
      set({ [key]: value } as Pick<Settings, typeof key>);
    }
    return result;
  },
}));
```

> The store's `set` now returns the validation result. Callers can show toasts on rejection.

- [ ] **Step C.1.4: Make Toggle controlled**

Edit `desktop/src/renderer/components/Toggle.tsx`. Replace with:

```tsx
interface Props {
  label?: string;
  on: boolean;
  onChange?: (next: boolean) => void;
  disabled?: boolean;
}

export function Toggle({ label, on, onChange, disabled }: Props) {
  return (
    <label
      className={`flex items-center gap-[10px] text-12 text-ink-1 ${disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}
    >
      <button
        type="button"
        onClick={() => !disabled && onChange?.(!on)}
        disabled={disabled}
        aria-pressed={on}
        className={`relative h-4 w-7 flex-shrink-0 rounded-pill border border-hairline-2 transition-colors duration-[120ms] ${on ? 'bg-neon' : 'bg-fog'} ${disabled ? '' : 'cursor-pointer'}`}
      >
        <span
          className={`absolute top-px h-3 w-3 rounded-full transition-[left] duration-[160ms] ease-[cubic-bezier(.2,.8,.2,1)] ${on ? 'left-[13px] bg-paper' : 'left-px bg-ink-2'}`}
        />
      </button>
      {label && <span>{label}</span>}
    </label>
  );
}
```

> Removed internal `useState`. Now fully controlled.

- [ ] **Step C.1.5: Wire every Toggle and select in settings.tsx**

Edit `desktop/src/renderer/screens/settings.tsx`. For each section, convert uncontrolled `<Toggle on />` and `<select onChange={() => stub(3)}>` to controlled.

`VaultSettings`:

```tsx
function VaultSettings() {
  const vaultPath = useSettings((s) => s.vaultPath);
  const dailyNoteEnabled = useSettings((s) => s.dailyNoteEnabled);
  const markdownFrontmatter = useSettings((s) => s.markdownFrontmatter);
  const autoLinkMentions = useSettings((s) => s.autoLinkMentions);
  const folderStructure = useSettings((s) => s.folderStructure);
  const setSetting = useSettings((s) => s.set);
  const onPick = async () => {
    const next = await window.gb.dialogs.pickVaultFolder();
    if (next) await setSetting('vaultPath', next);
  };
  return (
    <div>
      <SectionHeader title="vault" sub="where ghostbrain writes everything it catches." />
      <SettingRow
        label="vault path"
        sub={vaultPath}
        control={
          <Btn variant="secondary" size="sm" icon={<Lucide name="folder-open" size={13} />} onClick={onPick}>
            change
          </Btn>
        }
      />
      <SettingRow
        label="folder structure"
        sub="how ghostbrain organizes captured items"
        control={
          <select
            className={selectClass}
            value={folderStructure}
            onChange={(e) => void setSetting('folderStructure', e.target.value as FolderStructure)}
          >
            <option value="by-source">by source</option>
            <option value="by-date">by date</option>
            <option value="by-person">by person</option>
          </select>
        }
      />
      <SettingRow
        label="daily note"
        sub="capture digest appended to today's daily note"
        control={<Toggle on={dailyNoteEnabled} onChange={(v) => void setSetting('dailyNoteEnabled', v)} />}
      />
      <SettingRow
        label="markdown frontmatter"
        sub="add yaml metadata to every captured file"
        control={<Toggle on={markdownFrontmatter} onChange={(v) => void setSetting('markdownFrontmatter', v)} />}
      />
      <SettingRow
        label="auto-link mentions"
        sub='turn @names and #tags into [[wikilinks]]'
        control={<Toggle on={autoLinkMentions} onChange={(v) => void setSetting('autoLinkMentions', v)} />}
      />
    </div>
  );
}
```

Add the `FolderStructure` type import at the top: `import type { FolderStructure, LlmProvider, AudioRetention, TranscriptModel } from '../../shared/types';`.

Apply the same pattern to `PrivacySettings`, `MeetingSettings`. Each toggle/select reads from the store and writes through `setSetting`.

`PrivacySettings`:

```tsx
function PrivacySettings() {
  const cloudSync = useSettings((s) => s.cloudSync);
  const e2eEncryption = useSettings((s) => s.e2eEncryption);
  const telemetry = useSettings((s) => s.telemetry);
  const llmProvider = useSettings((s) => s.llmProvider);
  const setSetting = useSettings((s) => s.set);
  return (
    <div>
      <SectionHeader title="privacy" sub="ghostbrain is local-first. nothing leaves your machine unless you flip a switch." />
      <SettingRow label="cloud sync" sub="opt-in. encrypted at rest. you hold the key."
        control={<Toggle on={cloudSync} onChange={(v) => void setSetting('cloudSync', v)} />} />
      <SettingRow label="end-to-end encryption" sub="vault encrypted on disk with your passphrase"
        control={<Toggle on={e2eEncryption} onChange={(v) => void setSetting('e2eEncryption', v)} />} />
      <SettingRow label="telemetry" sub="anonymous crash reports. no message contents, ever."
        control={<Toggle on={telemetry} onChange={(v) => void setSetting('telemetry', v)} />} />
      <SettingRow label="LLM provider" sub="for transcript summarization & query"
        control={
          <select
            className={selectClass}
            value={llmProvider}
            onChange={(e) => void setSetting('llmProvider', e.target.value as LlmProvider)}
          >
            <option value="local">local (ollama)</option>
            <option value="anthropic">anthropic</option>
            <option value="openai">openai</option>
          </select>
        } />
    </div>
  );
}
```

`MeetingSettings`:

```tsx
function MeetingSettings() {
  const autoRecord = useSettings((s) => s.autoRecordFromCalendar);
  const diarize = useSettings((s) => s.diarizeSpeakers);
  const extract = useSettings((s) => s.extractActionItems);
  const retention = useSettings((s) => s.audioRetention);
  const model = useSettings((s) => s.transcriptModel);
  const setSetting = useSettings((s) => s.set);
  return (
    <div>
      <SectionHeader title="meetings" sub="how ghostbrain records, transcribes, and summarizes." />
      <SettingRow label="auto-record from calendar" sub="meetings tagged ⏺ in your calendar are auto-recorded"
        control={<Toggle on={autoRecord} onChange={(v) => void setSetting('autoRecordFromCalendar', v)} />} />
      <SettingRow label="diarize speakers" sub="separate who-said-what in the transcript"
        control={<Toggle on={diarize} onChange={(v) => void setSetting('diarizeSpeakers', v)} />} />
      <SettingRow label="extract action items" sub="ghostbrain pulls todos automatically"
        control={<Toggle on={extract} onChange={(v) => void setSetting('extractActionItems', v)} />} />
      <SettingRow label="audio retention" sub="how long to keep raw audio after transcription"
        control={
          <select className={selectClass} value={retention}
            onChange={(e) => void setSetting('audioRetention', e.target.value as AudioRetention)}>
            <option value="30d">30 days</option>
            <option value="7d">7 days</option>
            <option value="immediate">delete immediately</option>
            <option value="forever">keep forever</option>
          </select>
        } />
      <SettingRow label="transcript model" sub="whisper · runs locally"
        control={
          <select className={selectClass} value={model}
            onChange={(e) => void setSetting('transcriptModel', e.target.value as TranscriptModel)}>
            <option value="whisper-large-v3">whisper-large-v3</option>
            <option value="whisper-medium">whisper-medium</option>
          </select>
        } />
    </div>
  );
}
```

The `stub(3)` import becomes unused in this file once everything's wired — remove it (or leave it if any stub remains; check after the migration).

- [ ] **Step C.1.6: Verify persistence**

```bash
cd desktop
npm run typecheck && npm run lint && npm test
npm run dev
```

In the running app:
1. Navigate to Settings → Privacy. Toggle "telemetry" on.
2. Quit Electron (Cmd+Q).
3. Relaunch (`npm run dev` again).
4. Navigate to Settings → Privacy. Confirm "telemetry" is still on.
5. Toggle off, repeat to confirm it persists.
6. Test a select: change LLM provider to anthropic, restart, confirm.

- [ ] **Step C.1.7: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): wire all settings toggles and selects to real persistence

Schema extended with 13 keys covering vault, privacy, and meetings sections.
Toggle becomes fully controlled (no internal useState). All selects bind to
store keys. Set returns a validation result (implementation lands in D.3)."
```

---

## Task C.2: Implement density visually

**Files:**
- Modify: `desktop/src/renderer/styles.css`
- Possibly modify: a few components to add `gb-row` / `gb-topbar` / etc. classes if not already present

- [ ] **Step C.2.1: Add density CSS rules**

Append to `desktop/src/renderer/styles.css`:

```css
/* density: compact tightens vertical rhythm across key surfaces */
[data-density='compact'] .gb-topbar { height: 48px; }
[data-density='compact'] .gb-statusbar { height: 22px; }
[data-density='compact'] .gb-navrow { padding-top: 4px; padding-bottom: 4px; }
[data-density='compact'] .gb-sidenav { padding-top: 6px; padding-bottom: 6px; }
[data-density='compact'] .gb-setting-row { padding-top: 10px; padding-bottom: 10px; }
[data-density='compact'] .gb-panel-header { padding-top: 8px; padding-bottom: 8px; padding-left: 12px; padding-right: 12px; }
[data-density='compact'] .gb-panel-body { padding: 8px; }
```

- [ ] **Step C.2.2: Confirm component classes are in place**

The Tailwind migrations in B.2.a/b should have added these class names. Audit:

```bash
cd desktop
git grep -n "gb-topbar\|gb-statusbar\|gb-navrow\|gb-sidenav\|gb-setting-row\|gb-panel-header\|gb-panel-body" src/renderer/
```

Each should appear in:
- `gb-topbar`: `components/TopBar.tsx`
- `gb-statusbar`: `components/StatusBar.tsx`
- `gb-navrow`: `components/Sidebar.tsx` (NavRow)
- `gb-sidenav`: `components/Sidebar.tsx` (the `<nav>` element)
- `gb-setting-row`: `screens/settings.tsx` (SettingRow)
- `gb-panel-header`: `components/Panel.tsx` (the `<header>`)
- `gb-panel-body`: `components/Panel.tsx` (the body div)

If any are missing, add them to the corresponding component's className. Example: in Panel.tsx, the header element gets `className="gb-panel-header flex items-center gap-[10px] border-b border-hairline px-4 py-3"`.

- [ ] **Step C.2.3: Verify the density toggle has effect**

```bash
npm run dev
```

Navigate to Settings → Display. Toggle density to "compact". Visually confirm:
- Top bar gets shorter
- Status bar gets shorter
- Nav rows in sidebar tighten
- Settings rows tighten
- Panels (e.g. on Today screen) tighten

Toggle back to "comfy" and confirm it expands.

- [ ] **Step C.2.4: typecheck + lint + test**

All pass.

- [ ] **Step C.2.5: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): density toggle has real visual effect

[data-density='compact'] tightens top bar, status bar, sidebar nav rows,
settings rows, and panel padding. Components carry stable hook classes
(gb-topbar, gb-navrow, etc.) so density rules can target them."
```

---

## Task C.3: Account section honest

**Files:**
- Modify: `desktop/src/renderer/screens/settings.tsx`

- [ ] **Step C.3.1: Replace the AccountSettings component**

Edit `desktop/src/renderer/screens/settings.tsx`. Replace the `AccountSettings` function with:

```tsx
function AccountSettings() {
  return (
    <div>
      <SectionHeader title="account" sub="ghostbrain runs locally — no account needed for now." />
      <div className="rounded-lg border border-hairline bg-vellum p-6">
        <div className="flex items-start gap-3">
          <Lucide name="info" size={16} color="var(--ink-2)" className="mt-1" />
          <div className="flex-1 leading-[1.4]">
            <div className="text-13 font-medium text-ink-0">no sign-in yet</div>
            <p className="mt-1 text-12 text-ink-2">
              ghostbrain is local-first. accounts, sync, and the pro tier are coming in a future
              release. for now, everything runs on your machine and the vault on disk is the only
              source of truth.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
```

> The "Connected devices", "plan", and "Sign out" rows are gone. The Pill, the avatar, and the hardcoded email are gone.

- [ ] **Step C.3.2: Verify**

```bash
cd desktop
npm run typecheck && npm run lint && npm test
npm run dev   # navigate to Settings → Account, confirm honest empty state renders
```

- [ ] **Step C.3.3: Commit**

```bash
git add desktop/src/renderer/screens/settings.tsx
git commit -m "fix(desktop): account section honest empty state

Drops the hard-coded 'theo · ghostbrain pro' fiction. Tells users that
sign-in is coming later and that ghostbrain runs locally for now."
```

---

## Task D.1: ErrorBoundary

**Files:**
- Create: `desktop/src/renderer/components/ErrorBoundary.tsx`
- Modify: `desktop/src/renderer/main.tsx`

- [ ] **Step D.1.1: Implement the ErrorBoundary**

Create `desktop/src/renderer/components/ErrorBoundary.tsx`:

```tsx
import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.error('Renderer error:', error, info.componentStack);
    }
  }

  reload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.error) {
      return (
        <div className="flex h-full items-center justify-center bg-paper p-8">
          <div className="max-w-[480px] rounded-lg border border-oxblood/30 bg-oxblood/10 p-6">
            <h2 className="m-0 font-display text-22 font-semibold tracking-tight-x text-ink-0">
              ghostbrain hit a snag.
            </h2>
            <p className="mt-3 text-13 text-ink-1">
              the renderer process threw an error and stopped drawing. you can reload to recover —
              your settings and vault are unaffected.
            </p>
            <pre className="mt-4 overflow-auto rounded-sm bg-paper p-3 font-mono text-11 text-ink-2">
              {this.state.error.message}
            </pre>
            <button
              type="button"
              onClick={this.reload}
              className="mt-4 cursor-pointer rounded-r6 border border-transparent bg-neon px-[18px] py-[11px] font-body text-14 font-medium text-[#0E0F12] transition-all duration-[120ms] hover:bg-neon-dark"
            >
              reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
```

- [ ] **Step D.1.2: Wrap App in main.tsx**

Edit `desktop/src/renderer/main.tsx`. Replace with:

```tsx
import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import './styles.css';

const container = document.getElementById('root');
if (!container) throw new Error('root element missing');
createRoot(container).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);
```

- [ ] **Step D.1.3: Smoke-test the boundary**

Temporarily edit any screen to throw — e.g. in `today.tsx` add `if (Math.random() > 2) {} else throw new Error('test boundary')` at the top of the component (always-throw). Run `npm run dev` and confirm the fallback panel renders. Click "reload" and confirm it tries again.

Then revert the temp throw before committing.

- [ ] **Step D.1.4: typecheck + lint + test**

```bash
npm run typecheck
npm run lint
npm test
```

All pass.

- [ ] **Step D.1.5: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): ErrorBoundary wraps the App tree

A rendering error in any screen now shows a recovery panel with the error
message and a reload button instead of a blank window."
```

---

## Task D.2: Content-Security-Policy

**Files:**
- Modify: `desktop/src/renderer/index.html`

- [ ] **Step D.2.1: Add the CSP meta tag**

Edit `desktop/src/renderer/index.html`. Add a `<meta>` tag inside `<head>` right after the charset/viewport tags:

```html
<meta
  http-equiv="Content-Security-Policy"
  content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self';"
/>
```

- [ ] **Step D.2.2: Run dev, look for CSP violations**

```bash
cd desktop
npm run dev
```

Open DevTools (Cmd+Opt+I or View → Toggle Developer Tools). Console tab. Click through every screen. Look for `Refused to ...` errors.

- Tailwind v4 injects `<style>` blocks at runtime; these are why we keep `'unsafe-inline'` for styles.
- Inline `style={{}}` props in React do *not* trigger CSP for inline styles — they're attribute-set, not `<style>` blocks. Some browsers behave differently; verify in Electron's actual Chromium.
- The `gb-noise` data-URL stays valid because we allow `data:` for `img-src`.

If a violation appears, either:
- Fix the source (don't introduce new external domains; remove the offending inline script if any).
- Adjust the CSP minimally (e.g. add a specific origin) and document why.

- [ ] **Step D.2.3: typecheck + lint + test**

All pass.

- [ ] **Step D.2.4: Commit**

```bash
git add desktop/src/renderer/index.html
git commit -m "feat(desktop): add Content-Security-Policy meta tag

Restricts default-src to self. style-src allows 'unsafe-inline' for
Tailwind v4's runtime style injection and the Google Fonts CSS import.
img-src allows data: for the gb-noise SVG."
```

---

## Task D.3: IPC handler input validation with zod

**Files:**
- Modify: `desktop/package.json` (adds zod)
- Create: `desktop/src/shared/settings-schema.ts`
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/src/main/dialogs.ts` (no change to dialogs; openPath gets validation here)
- Modify: `desktop/src/preload/index.ts` (no change — already returns the result type from A.4)
- Modify: `desktop/src/renderer/screens/vault.tsx` (handles error result)
- Modify: `desktop/src/renderer/screens/settings.tsx` (already updated in C.1 to await the result)

- [ ] **Step D.3.1: Install zod**

```bash
cd desktop
npm install zod
```

- [ ] **Step D.3.2: Build the settings schema**

Create `desktop/src/shared/settings-schema.ts`:

```ts
import { z } from 'zod';

export const settingsSchema = z.object({
  theme: z.enum(['dark', 'light']),
  density: z.enum(['comfortable', 'compact']),
  vaultPath: z.string().min(1),

  dailyNoteEnabled: z.boolean(),
  markdownFrontmatter: z.boolean(),
  autoLinkMentions: z.boolean(),

  cloudSync: z.boolean(),
  e2eEncryption: z.boolean(),
  telemetry: z.boolean(),
  llmProvider: z.enum(['local', 'anthropic', 'openai']),

  autoRecordFromCalendar: z.boolean(),
  diarizeSpeakers: z.boolean(),
  extractActionItems: z.boolean(),
  audioRetention: z.enum(['30d', '7d', 'immediate', 'forever']),
  transcriptModel: z.enum(['whisper-large-v3', 'whisper-medium']),

  folderStructure: z.enum(['by-source', 'by-date', 'by-person']),
});

export type SettingsKey = keyof z.infer<typeof settingsSchema>;
```

- [ ] **Step D.3.3: Validate in IPC handlers**

Edit `desktop/src/main/index.ts`. Replace the IPC handler block with:

```ts
import { settingsSchema } from '../shared/settings-schema';

ipcMain.handle('gb:settings:getAll', () => settings.getAll());

ipcMain.handle('gb:settings:set', (_e, key: unknown, value: unknown) => {
  if (typeof key !== 'string' || !(key in settingsSchema.shape)) {
    return { ok: false, error: `Unknown setting: ${String(key)}` };
  }
  const fieldSchema = settingsSchema.shape[key as keyof typeof settingsSchema.shape];
  const parsed = fieldSchema.safeParse(value);
  if (!parsed.success) {
    return { ok: false, error: `Invalid value for ${key}: ${parsed.error.issues[0]?.message ?? 'validation failed'}` };
  }
  settings.setKey(key as keyof Settings, parsed.data as Settings[keyof Settings]);
  return { ok: true };
});

ipcMain.handle('gb:dialogs:pickVaultFolder', () => pickVaultFolder());

ipcMain.handle('gb:shell:openPath', async (_e, p: unknown) => {
  if (typeof p !== 'string') {
    return { ok: false, error: 'openPath: path must be a string' };
  }
  const vaultPath = settings.getAll().vaultPath;
  // Allow opening the configured vault path itself or any path under it.
  // Reject anything else to prevent the renderer from opening arbitrary paths.
  const normalized = p.replace(/\\/g, '/');
  const allowed = vaultPath.replace(/\\/g, '/');
  if (normalized !== allowed && !normalized.startsWith(allowed + '/')) {
    return { ok: false, error: 'openPath: only the vault path is allowed' };
  }
  await shell.openPath(p);
  return { ok: true };
});
```

The `import type { Settings } from '../shared/types'` should already be at the top of the file from earlier tasks; verify.

- [ ] **Step D.3.4: Surface errors in the renderer**

Edit `desktop/src/renderer/screens/vault.tsx`. Replace the `onOpen` handler with:

```tsx
const onOpen = async () => {
  const result = await window.gb.shell.openPath(vaultPath);
  if (!result.ok) {
    useToasts.getState().push(result.error);
  }
};
```

Add the import: `import { useToasts } from '../stores/toast';`.

For settings: the `setSetting` call in `screens/settings.tsx` already returns the result (after C.1). Update each control's `onChange` to surface errors:

```tsx
onChange={async (v) => {
  const r = await setSetting('dailyNoteEnabled', v);
  if (!r.ok) useToasts.getState().push(r.error);
}}
```

That said, since the schema is enforced on the renderer side too (every control has correct types), validation rejections shouldn't happen in normal flow — they catch programmer error. Still, the surface should exist.

To avoid noisy code, write a small helper at the top of `screens/settings.tsx`:

```tsx
import { useToasts } from '../stores/toast';

async function trySet<K extends keyof Settings>(
  setSetting: (k: K, v: Settings[K]) => Promise<{ ok: true } | { ok: false; error: string }>,
  key: K,
  value: Settings[K],
) {
  const r = await setSetting(key, value);
  if (!r.ok) useToasts.getState().push(r.error);
}
```

And use `onChange={(v) => void trySet(setSetting, 'dailyNoteEnabled', v)}` for each control.

(Do this once you've confirmed `useToasts` and the helper compile; the verbose inline form is also fine if you prefer.)

- [ ] **Step D.3.5: Smoke test from DevTools**

```bash
cd desktop
npm run dev
```

Open DevTools (Cmd+Opt+I). At the console:

```js
await window.gb.settings.set('theme', 'rainbow')
// expected: { ok: false, error: "Invalid value for theme: ..." }

await window.gb.settings.set('madeUpKey', 'whatever')
// expected: { ok: false, error: "Unknown setting: madeUpKey" }

await window.gb.shell.openPath('/etc/passwd')
// expected: { ok: false, error: "openPath: only the vault path is allowed" }
```

All three return `{ ok: false }` with descriptive errors.

- [ ] **Step D.3.6: typecheck + lint + test**

All pass.

- [ ] **Step D.3.7: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): validate IPC handler inputs with zod

settings:set rejects unknown keys and invalid values. shell:openPath
restricts to the configured vault path or paths under it. Renderer surfaces
rejections as toasts. Bridge return types are now { ok: true | false }."
```

---

## Task D.4: App icon

**Files:**
- Create: `desktop/build/icon.png`
- Create: `desktop/build/icon.icns`
- Create: `desktop/build/icon.ico`
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/electron-builder.yml`

- [ ] **Step D.4.1: Render a 1024×1024 master icon**

Generate the master PNG. Easiest approach: render the existing `Ghost` SVG glyph at 1024×1024 onto a deep cool-ink (#0E0F12) rounded-rect background. Steps:

```bash
cd desktop
mkdir -p build
```

If you have ImageMagick or Inkscape, render from `src/renderer/public/assets/glyph.svg` (the existing glyph). Or use any vector tool to produce `build/icon.png` at 1024×1024. The icon should be:

- 1024×1024 transparent or background-filled PNG
- Centered ghost glyph in neon (#C5FF3D) with eyes in paper (#0E0F12)
- ~20% margin around the glyph (Apple's HIG recommends a safe zone)

If you don't have a tool handy, a lower-fidelity placeholder is fine for this slice — track it as a follow-up to commission a polished icon. Document the placeholder choice in the commit.

- [ ] **Step D.4.2: Generate macOS .icns**

```bash
cd desktop/build
mkdir icon.iconset
sips -z 16 16     icon.png --out icon.iconset/icon_16x16.png
sips -z 32 32     icon.png --out icon.iconset/icon_16x16@2x.png
sips -z 32 32     icon.png --out icon.iconset/icon_32x32.png
sips -z 64 64     icon.png --out icon.iconset/icon_32x32@2x.png
sips -z 128 128   icon.png --out icon.iconset/icon_128x128.png
sips -z 256 256   icon.png --out icon.iconset/icon_128x128@2x.png
sips -z 256 256   icon.png --out icon.iconset/icon_256x256.png
sips -z 512 512   icon.png --out icon.iconset/icon_256x256@2x.png
sips -z 512 512   icon.png --out icon.iconset/icon_512x512.png
cp icon.png       icon.iconset/icon_512x512@2x.png
iconutil -c icns icon.iconset
rm -rf icon.iconset
ls icon.icns
```

(macOS-only commands — `sips` and `iconutil` ship with macOS. On Windows or Linux, use `electron-icon-builder` or similar; document the alternative.)

- [ ] **Step D.4.3: Generate Windows .ico**

Use a converter like `png-to-ico` (npm) or any image tool that produces multi-resolution `.ico`:

```bash
npx --yes png-to-ico icon.png > icon.ico
```

(Adjust if `png-to-ico` requires specific input sizes — generate intermediate PNGs at 16/32/48/64/128/256 first if needed.)

- [ ] **Step D.4.4: Set the dev window icon**

Edit `desktop/src/main/index.ts`. Locate the `BrowserWindow` constructor call and add:

```ts
import { join } from 'node:path';

// ... inside createWindow():
const win = new BrowserWindow({
  width: 1280,
  height: 800,
  minWidth: 1024,
  minHeight: 720,
  show: false,
  backgroundColor: '#0E0F12',
  titleBarStyle: isMac ? 'hiddenInset' : 'default',
  trafficLightPosition: isMac ? { x: 14, y: 14 } : undefined,
  icon: join(app.getAppPath(), 'build/icon.png'),  // <-- add this
  webPreferences: {
    preload: join(__dirname, '../preload/index.js'),
    contextIsolation: true,
    sandbox: true,
  },
});
```

(The icon path uses `app.getAppPath()` so it resolves correctly in both dev and built contexts.)

- [ ] **Step D.4.5: Reference icons in electron-builder.yml**

Edit `desktop/electron-builder.yml`. Replace with:

```yaml
appId: app.ghostbrain.desktop
productName: ghostbrain
directories:
  buildResources: build
mac:
  icon: build/icon.icns
win:
  icon: build/icon.ico
linux:
  icon: build/icon.png
```

> Slice 5 will flesh this out with targets, signing, and update channels. We're just landing the icon references now.

- [ ] **Step D.4.6: Verify**

```bash
cd desktop
npm run dev
```

On Mac: the dock icon shows the new icon (may require quitting Electron Helper from previous runs first; force-quit and relaunch).

- [ ] **Step D.4.7: Commit**

```bash
git add desktop/build/ desktop/src/main/index.ts desktop/electron-builder.yml
git commit -m "feat(desktop): app icon

1024x1024 master, .icns for macOS, .ico for Windows. Dev window icon set
via BrowserWindow constructor; electron-builder references for future
slice 5 packaging."
```

---

## Task D.5: Window state persistence

**Files:**
- Create: `desktop/src/main/window-state.ts`
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/src/main/settings.ts` (optional — extend the JSON config to include window state)

- [ ] **Step D.5.1: Implement a small window-state helper**

We could install `electron-window-state`, but rolling a 30-line equivalent that uses our existing JSON config is cleaner. Create `desktop/src/main/window-state.ts`:

```ts
import { app, BrowserWindow, screen } from 'electron';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';

interface WindowState {
  x?: number;
  y?: number;
  width: number;
  height: number;
  maximized: boolean;
}

const DEFAULTS: WindowState = { width: 1280, height: 800, maximized: false };

function statePath(): string {
  return join(app.getPath('userData'), 'window-state.json');
}

function read(): WindowState {
  const path = statePath();
  if (!existsSync(path)) return { ...DEFAULTS };
  try {
    const raw = readFileSync(path, 'utf-8');
    const parsed = JSON.parse(raw) as Partial<WindowState>;
    return { ...DEFAULTS, ...parsed };
  } catch {
    return { ...DEFAULTS };
  }
}

function inBounds(state: WindowState): boolean {
  if (state.x === undefined || state.y === undefined) return true;
  const displays = screen.getAllDisplays();
  return displays.some(
    (d) =>
      state.x! >= d.bounds.x &&
      state.y! >= d.bounds.y &&
      state.x! + state.width <= d.bounds.x + d.bounds.width &&
      state.y! + state.height <= d.bounds.y + d.bounds.height,
  );
}

export function loadInitialState(): WindowState {
  const state = read();
  if (!inBounds(state)) {
    return { ...DEFAULTS, maximized: state.maximized };
  }
  return state;
}

export function attachStatePersistence(win: BrowserWindow): void {
  const persist = () => {
    if (win.isDestroyed()) return;
    const isMaximized = win.isMaximized();
    const bounds = isMaximized ? win.getNormalBounds() : win.getBounds();
    const state: WindowState = {
      x: bounds.x,
      y: bounds.y,
      width: bounds.width,
      height: bounds.height,
      maximized: isMaximized,
    };
    const path = statePath();
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify(state, null, 2), 'utf-8');
  };
  win.on('resize', persist);
  win.on('move', persist);
  win.on('close', persist);
}
```

- [ ] **Step D.5.2: Use it in main/index.ts**

Edit `desktop/src/main/index.ts`. Update `createWindow`:

```ts
import { loadInitialState, attachStatePersistence } from './window-state';

function createWindow() {
  const isMac = process.platform === 'darwin';
  const initial = loadInitialState();
  const win = new BrowserWindow({
    x: initial.x,
    y: initial.y,
    width: initial.width,
    height: initial.height,
    minWidth: 1024,
    minHeight: 720,
    show: false,
    backgroundColor: '#0E0F12',
    titleBarStyle: isMac ? 'hiddenInset' : 'default',
    trafficLightPosition: isMac ? { x: 14, y: 14 } : undefined,
    icon: join(app.getAppPath(), 'build/icon.png'),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: true,
    },
  });
  if (initial.maximized) win.maximize();
  attachStatePersistence(win);
  win.on('ready-to-show', () => win.show());
  // … existing loadURL/loadFile branch unchanged
}
```

- [ ] **Step D.5.3: Verify**

```bash
cd desktop
npm run dev
```

Resize the window. Move it. Quit. Relaunch. The window should appear at the same size and position.

Maximize the window. Quit. Relaunch. The window should appear maximized.

- [ ] **Step D.5.4: typecheck + lint + test**

All pass.

- [ ] **Step D.5.5: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): window state persistence

Position, size, and maximized state are saved to window-state.json in
userData on resize/move/close, and restored on launch. Off-screen state
is ignored (e.g. monitor disconnected) and falls back to default size."
```

---

## Task D.6: Native menu bar

**Files:**
- Create: `desktop/src/main/menu.ts`
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/src/preload/index.ts` (adds `gb:nav:settings` listener)
- Modify: `desktop/src/shared/types.ts` (extends `GbBridge` with nav event subscription)
- Modify: `desktop/src/renderer/App.tsx` (subscribes to nav events)

- [ ] **Step D.6.1: Build the menu**

Create `desktop/src/main/menu.ts`:

```ts
import { Menu, BrowserWindow, app, shell, type MenuItemConstructorOptions } from 'electron';

export function buildAppMenu(): void {
  const isMac = process.platform === 'darwin';
  const isDev = !!process.env.ELECTRON_RENDERER_URL;

  const macAppMenu: MenuItemConstructorOptions = {
    label: app.name,
    submenu: [
      { role: 'about' },
      { type: 'separator' },
      {
        label: 'Settings…',
        accelerator: 'Cmd+,',
        click: () => {
          BrowserWindow.getAllWindows()[0]?.webContents.send('gb:nav:settings');
        },
      },
      { type: 'separator' },
      { role: 'services' },
      { type: 'separator' },
      { role: 'hide' },
      { role: 'hideOthers' },
      { role: 'unhide' },
      { type: 'separator' },
      { role: 'quit' },
    ],
  };

  const fileMenu: MenuItemConstructorOptions = {
    label: 'File',
    submenu: isMac
      ? [{ role: 'close' }]
      : [
          {
            label: 'Settings…',
            accelerator: 'Ctrl+,',
            click: () => {
              BrowserWindow.getAllWindows()[0]?.webContents.send('gb:nav:settings');
            },
          },
          { type: 'separator' },
          { role: 'quit' },
        ],
  };

  const editMenu: MenuItemConstructorOptions = {
    label: 'Edit',
    submenu: [
      { role: 'undo' },
      { role: 'redo' },
      { type: 'separator' },
      { role: 'cut' },
      { role: 'copy' },
      { role: 'paste' },
      ...(isMac
        ? [
            { role: 'pasteAndMatchStyle' as const },
            { role: 'delete' as const },
            { role: 'selectAll' as const },
          ]
        : [{ role: 'delete' as const }, { type: 'separator' as const }, { role: 'selectAll' as const }]),
    ],
  };

  const viewMenu: MenuItemConstructorOptions = {
    label: 'View',
    submenu: [
      ...(isDev
        ? [
            { role: 'reload' as const },
            { role: 'forceReload' as const },
            { role: 'toggleDevTools' as const },
            { type: 'separator' as const },
          ]
        : []),
      { role: 'resetZoom' },
      { role: 'zoomIn' },
      { role: 'zoomOut' },
      { type: 'separator' },
      { role: 'togglefullscreen' },
    ],
  };

  const windowMenu: MenuItemConstructorOptions = {
    label: 'Window',
    submenu: isMac
      ? [
          { role: 'minimize' },
          { role: 'zoom' },
          { type: 'separator' },
          { role: 'front' },
        ]
      : [{ role: 'minimize' }, { role: 'zoom' }, { role: 'close' }],
  };

  const helpMenu: MenuItemConstructorOptions = {
    label: 'Help',
    submenu: [
      {
        label: 'Open project on GitHub',
        click: () => void shell.openExternal('https://github.com/nikrich/ghost-brain'),
      },
    ],
  };

  const template: MenuItemConstructorOptions[] = isMac
    ? [macAppMenu, fileMenu, editMenu, viewMenu, windowMenu, helpMenu]
    : [fileMenu, editMenu, viewMenu, windowMenu, helpMenu];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}
```

- [ ] **Step D.6.2: Call it from main**

Edit `desktop/src/main/index.ts`. After `app.whenReady().then(createWindow);` add:

```ts
import { buildAppMenu } from './menu';

app.whenReady().then(() => {
  buildAppMenu();
  createWindow();
});
```

(Replace the existing `app.whenReady().then(createWindow)` line — combine the calls into the body.)

- [ ] **Step D.6.3: Bridge the nav event to the renderer**

Edit `desktop/src/shared/types.ts`. Extend `GbBridge`:

```ts
export interface GbBridge {
  settings: { /* ... */ };
  dialogs: { /* ... */ };
  shell: { /* ... */ };
  platform: NodeJS.Platform;
  on(channel: 'nav:settings', listener: () => void): () => void;
}
```

The new `on` method takes a channel and a listener; returns an unsubscribe function.

Edit `desktop/src/preload/index.ts`. Extend the bridge:

```ts
import { contextBridge, ipcRenderer } from 'electron';
import type { GbBridge, Settings } from '../shared/types';

const bridge: GbBridge = {
  // ... existing settings/dialogs/shell/platform
  on: (channel, listener) => {
    const wrapped = () => listener();
    const ipcChannel = `gb:${channel}`;
    ipcRenderer.on(ipcChannel, wrapped);
    return () => {
      ipcRenderer.off(ipcChannel, wrapped);
    };
  },
};

contextBridge.exposeInMainWorld('gb', bridge);
export type { Settings };
```

- [ ] **Step D.6.4: Subscribe in App.tsx**

Edit `desktop/src/renderer/App.tsx`. Add an effect that subscribes to the nav channel:

```tsx
import { useEffect } from 'react';
import { useSettings } from './stores/settings';
import { useNavigation } from './stores/navigation';
// ... existing imports

export default function App() {
  const { theme, density, ready, hydrate } = useSettings();
  const active = useNavigation((s) => s.active);
  const setActive = useNavigation((s) => s.setActive);

  useEffect(() => { hydrate(); }, [hydrate]);
  useEffect(() => {
    if (!ready) return;
    document.body.dataset.theme = theme;
    document.body.dataset.density = density;
  }, [theme, density, ready]);
  useEffect(() => {
    return window.gb.on('nav:settings', () => setActive('settings'));
  }, [setActive]);

  // ... rest unchanged
}
```

- [ ] **Step D.6.5: Verify**

```bash
cd desktop
npm run dev
```

On Mac: the menu bar shows "ghostbrain | File | Edit | View | Window | Help". Click "ghostbrain" → "Settings…" — the renderer should switch to the Settings screen. Press Cmd+, anywhere — same.

Test cut/copy/paste in any text input (e.g. the vault path or a future search field).

- [ ] **Step D.6.6: typecheck + lint + test**

All pass.

- [ ] **Step D.6.7: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): native application menu

Standard macOS menu structure (app menu / File / Edit / View / Window /
Help) with platform-aware fallback for Windows and Linux. Cmd+, on Mac
(Ctrl+, on others) opens Settings via a typed nav event bridged to the
renderer. Dev menu items (Reload, DevTools) appear only in dev mode."
```

---

## Task E.1: Toaster — kind-aware

**Files:**
- Modify: `desktop/src/renderer/stores/toast.ts`
- Modify: `desktop/src/renderer/components/Toaster.tsx`
- Modify: `desktop/src/renderer/components/ErrorBoundary.tsx`

- [ ] **Step E.1.1: Extend the toast store**

Replace `desktop/src/renderer/stores/toast.ts` with:

```ts
import { create } from 'zustand';

export type ToastKind = 'info' | 'success' | 'error';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastState {
  toasts: Toast[];
  push: (kind: ToastKind, message: string) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

const DURATIONS: Record<ToastKind, number> = {
  info: 3500,
  success: 3500,
  error: 6000,
};

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push: (kind, message) => {
    const id = nextId++;
    set({ toasts: [...get().toasts, { id, kind, message }] });
    setTimeout(() => get().dismiss(id), DURATIONS[kind]);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));

export const toast = {
  info: (m: string) => useToasts.getState().push('info', m),
  success: (m: string) => useToasts.getState().push('success', m),
  error: (m: string) => useToasts.getState().push('error', m),
};

// Backwards-compat helper used by stub buttons; will go away as Slices 2-4 wire real handlers.
export const stub = (slice: number) => toast.info(`wired in Slice ${slice}`);
```

> The `push` API changed signature (`push(kind, message)` instead of `push(message)`). Existing callers using `useToasts.getState().push(message)` need updating — there's only one such call (in vault.tsx after D.3, plus the `stub` helper itself which is in this file).

Search and update:

```bash
git grep -n "useToasts.getState().push" desktop/src/renderer/
```

For each match, change `.push('error message')` to `.push('error', 'error message')` — or better, change the call site to use the new `toast.error('error message')` helper.

- [ ] **Step E.1.2: Render kind-aware Toaster**

Replace `desktop/src/renderer/components/Toaster.tsx` with:

```tsx
import { useToasts, type ToastKind } from '../stores/toast';

const KIND_CLASSES: Record<ToastKind, string> = {
  info: 'border-hairline-2 bg-vellum text-ink-0',
  success: 'border-neon/40 bg-neon/12 text-neon',
  error: 'border-oxblood/40 bg-oxblood/15 text-oxblood',
};

export function Toaster() {
  const toasts = useToasts((s) => s.toasts);
  return (
    <div className="pointer-events-none fixed bottom-10 right-5 z-[1000] flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          role={t.kind === 'error' ? 'alert' : 'status'}
          className={`rounded-md border px-[14px] py-[10px] font-mono text-12 shadow-card ${KIND_CLASSES[t.kind]}`}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step E.1.3: ErrorBoundary fires a toast in addition to the panel**

Edit `desktop/src/renderer/components/ErrorBoundary.tsx`. Update `componentDidCatch`:

```tsx
componentDidCatch(error: Error, info: ErrorInfo) {
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.error('Renderer error:', error, info.componentStack);
  }
  // Best-effort toast — works once toast store is mounted; if the error happened
  // before App rendered, the toast helper is still safe to call (it just queues).
  import('../stores/toast').then(({ toast }) => {
    toast.error(error.message || 'Something went wrong');
  });
}
```

> The dynamic import avoids a circular dep risk if the toast store ever depends on something that errors.

- [ ] **Step E.1.4: Update vault.tsx and settings.tsx to use the helpers**

Edit `desktop/src/renderer/screens/vault.tsx`:

```tsx
import { toast } from '../stores/toast';
// ...
const onOpen = async () => {
  const result = await window.gb.shell.openPath(vaultPath);
  if (!result.ok) toast.error(result.error);
};
```

Edit `desktop/src/renderer/screens/settings.tsx` `trySet` helper to use `toast.error`:

```tsx
import { toast } from '../stores/toast';
// ...
async function trySet<K extends keyof Settings>(
  setSetting: (k: K, v: Settings[K]) => Promise<{ ok: true } | { ok: false; error: string }>,
  key: K,
  value: Settings[K],
) {
  const r = await setSetting(key, value);
  if (!r.ok) toast.error(r.error);
}
```

- [ ] **Step E.1.5: Verify**

```bash
cd desktop
npm run dev
```

In the running app, in DevTools console:

```js
window.dispatchEvent(new Event('test'));  // sanity
useToasts // not directly exposed; instead trigger a real path:
await window.gb.settings.set('theme', 'rainbow')  // returns ok: false
// observe an error toast appears
```

Or trigger a vault open with an out-of-vault path (won't be possible from the UI — but is from DevTools):

```js
await window.gb.shell.openPath('/etc/passwd')
// toast appears with "openPath: only the vault path is allowed"
```

Toggle some real settings — they should NOT toast (success path).

- [ ] **Step E.1.6: typecheck + lint + test**

All pass.

- [ ] **Step E.1.7: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): kind-aware toasts (info/success/error)

push() signature changes to (kind, message). New toast.{info,success,error}
helpers wrap the store. Toaster renders kind-specific styling and
role=alert/status for screen readers. ErrorBoundary surfaces an error toast
alongside the recovery panel. Existing stub() preserved."
```

---

## Self-review

This plan is checked against `docs/superpowers/specs/2026-05-08-desktop-shell-cleanup-design.md`:

| Spec section | Tasks | Notes |
|--------------|-------|-------|
| Phase A.1 — replace electron-store | A.1 | Atomic write, schema version, defaults merge, corrupt-fallback all tested |
| Phase A.2 — sandbox: true | A.2 | Includes a STOP rule if the bridge breaks |
| Phase A.3 — lucide-react | A.3 | Includes dev-only console.warn for unknown names |
| Phase A.4 — shared types | A.4 | Plus tsconfig.shared.json wiring |
| Phase A.5 — csstype augmentation | A.5 | Removes existing casts |
| Phase A.6 — ESLint peer-dep | A.6 | Two-stage: try upgrade, fall back to pin |
| Phase B.1 — extend @theme | B.1 | Tokens enumerated explicitly |
| Phase B.2 — per-component migration | B.2.a, B.2.b, B.2.c, B.2.d, B.2.e, B.2.f | Six tasks, ordered leaves → screens |
| Phase B.3 — hex audit | B.3 | Grep + per-match decision |
| Phase B.4 — light-mode walkthrough | B.4 | Manual walk + per-finding fixes |
| Phase C.1 — wire toggles | C.1 | Schema extension + Toggle controlled + each section's selects/toggles |
| Phase C.2 — density visual | C.2 | CSS rules + class hooks on TopBar/StatusBar/Sidebar/SettingRow/Panel |
| Phase C.3 — account honest | C.3 | Replaces hardcoded "theo · pro" with empty state |
| Phase D.1 — ErrorBoundary | D.1 | Includes a smoke-test step (temporary throw) |
| Phase D.2 — CSP | D.2 | Documented allowances and verification |
| Phase D.3 — IPC validation | D.3 | zod schema + handler validation + path restriction for openPath |
| Phase D.4 — app icon | D.4 | Master + .icns + .ico + dev window icon + builder reference |
| Phase D.5 — window state | D.5 | Hand-rolled state file + bounds check |
| Phase D.6 — native menu | D.6 | Mac/Win/Linux templates + Cmd+, → settings via nav bridge |
| Phase E — toaster real | E.1 | Kind-aware + ErrorBoundary integration + helper API |
| Acceptance criteria 1–23 | covered | 1 (no non-desktop changes) is an enforced rule, others map directly to tasks |

**Placeholder check:** No "TBD"/"TODO"/"implement later". One step explicitly notes "track follow-up" for icon polish if a designer-quality master isn't generated in the implementation session — that's a deliberate scope check, not a placeholder.

**Type consistency:**
- `Settings` extended once in C.1; main defaults updated in same task; renderer store updated in same task; zod schema added in D.3 mirroring the same shape. All in one place per task.
- `GbBridge` extended once in A.4 (return types) and once in D.6 (`on` method); preload index follows.
- `toast.{info,success,error}` introduced in E.1; existing `stub()` preserved for compat.

**Scope:** every task explicitly stays within `desktop/`. Acceptance criterion 1 enforces it. No Python-side work.
