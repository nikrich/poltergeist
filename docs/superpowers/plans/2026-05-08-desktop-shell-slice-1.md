# Ghostbrain Desktop Shell — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a production-grade Electron + React + TypeScript shell that renders all 6 ghostbrain screens at the design's visual fidelity, with persisted settings, on macOS and Windows. No Python integration yet.

**Architecture:** electron-vite drives the build. Main process owns window lifecycle and electron-store; renderer is React 18 + Tailwind v4 styled from CSS-first design tokens. Cross-screen state is split across three Zustand stores (navigation, meeting, settings). The settings store hydrates from disk via a typed contextBridge preload, then writes through to electron-store on every mutation.

**Tech Stack:** Electron, electron-vite, React 18, TypeScript (strict), Tailwind v4, Zustand, electron-store, Vitest + React Testing Library, ESLint, Prettier.

**Spec:** `docs/superpowers/specs/2026-05-08-desktop-shell-slice-1-design.md`

---

## File Structure

Files created in `desktop/`:

| Path | Responsibility |
|------|----------------|
| `package.json`, `tsconfig.json`, `tsconfig.node.json`, `tsconfig.web.json` | Project config |
| `electron.vite.config.ts` | Build pipeline |
| `electron-builder.yml` | Packaging placeholder for Slice 5 |
| `.eslintrc.cjs`, `.prettierrc` | Lint/format |
| `.gitignore` | Ignore `node_modules`, `out/`, `dist/` |
| `vitest.config.ts` | Test runner |
| `src/main/index.ts` | Window lifecycle, IPC handler registration |
| `src/main/settings.ts` | electron-store wrapper |
| `src/main/dialogs.ts` | Folder picker for vault path |
| `src/preload/index.ts` | Typed contextBridge: `window.gb` |
| `src/preload/types.ts` | Shared types between main, preload, renderer |
| `src/renderer/index.html`, `main.tsx`, `App.tsx` | Renderer entry |
| `src/renderer/styles.css` | Tailwind v4 + `@theme` design tokens + signature animations + font face |
| `src/renderer/components/{Btn,Pill,Eyebrow,Lucide,Ghost,Panel,Toggle,Toast,Sidebar,TopBar,StatusBar,WindowChrome}.tsx` | Shared UI |
| `src/renderer/screens/{today,connectors,meetings,capture,vault,settings}.tsx` | Screens |
| `src/renderer/stores/{navigation,meeting,settings,toast}.ts` | Zustand stores |
| `src/renderer/lib/mocks/{today,connectors,meetings,capture}.ts` | Stubbed data |
| `src/renderer/lib/{platform,shortcuts}.ts` | Platform helpers |
| `src/renderer/__tests__/App.test.tsx` | Smoke test |

Files preserved (then removed at end):
- `desktop/_prototype/` — the original HTML/JSX prototype, archived for visual reference during implementation, deleted before Slice 1 ships.

Files preserved permanently:
- `desktop/assets/` (connector SVGs, glyph, favicon)
- `desktop/fonts/` (GoogleSansFlex variable font)
- `desktop/colors_and_type.css` — kept and re-exported from `styles.css` so it remains the design-token source.

---

## Task 1: Archive prototype, scaffold npm project

**Files:**
- Move: `desktop/{*.jsx,*.html,colors_and_type.css,screens/}` → `desktop/_prototype/`
- Keep at `desktop/`: `assets/`, `fonts/`
- Create: `desktop/package.json`
- Create: `desktop/tsconfig.json`, `desktop/tsconfig.node.json`, `desktop/tsconfig.web.json`
- Create: `desktop/electron.vite.config.ts`
- Create: `desktop/.gitignore`
- Create: `desktop/electron-builder.yml`
- Create: `desktop/src/main/index.ts` (placeholder)
- Create: `desktop/src/preload/index.ts` (placeholder)
- Create: `desktop/src/renderer/index.html`
- Create: `desktop/src/renderer/main.tsx`
- Create: `desktop/src/renderer/App.tsx` (placeholder)

- [ ] **Step 1.1: Archive the prototype**

```bash
cd desktop
mkdir -p _prototype
mv index.html app.jsx app-shell.jsx tweaks-panel.jsx colors_and_type.css screens _prototype/
# Keep colors_and_type.css ALSO at the top level — it remains the design-token source
cp _prototype/colors_and_type.css .
ls
```

Expected: `_prototype/`, `assets/`, `colors_and_type.css`, `fonts/`.

- [ ] **Step 1.2: Initialize package.json**

Create `desktop/package.json`:

```json
{
  "name": "ghostbrain-desktop",
  "version": "0.1.0",
  "private": true,
  "main": "out/main/index.js",
  "scripts": {
    "dev": "electron-vite dev",
    "build": "electron-vite build",
    "preview": "electron-vite preview",
    "typecheck": "tsc --noEmit -p tsconfig.web.json && tsc --noEmit -p tsconfig.node.json",
    "lint": "eslint . --ext .ts,.tsx --max-warnings 0",
    "format": "prettier --write \"src/**/*.{ts,tsx,css,html}\"",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "electron-store": "^10.0.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zustand": "^5.0.0"
  },
  "devDependencies": {
    "@tailwindcss/vite": "^4.0.0",
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/react": "^16.0.0",
    "@types/node": "^22.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@typescript-eslint/eslint-plugin": "^8.0.0",
    "@typescript-eslint/parser": "^8.0.0",
    "@vitejs/plugin-react": "^4.3.0",
    "electron": "^32.0.0",
    "electron-vite": "^2.3.0",
    "eslint": "^9.0.0",
    "eslint-plugin-react": "^7.35.0",
    "eslint-plugin-react-hooks": "^5.0.0",
    "jsdom": "^25.0.0",
    "prettier": "^3.3.0",
    "tailwindcss": "^4.0.0",
    "typescript": "^5.6.0",
    "vitest": "^2.1.0"
  }
}
```

- [ ] **Step 1.3: Create tsconfig files**

Create `desktop/tsconfig.json`:

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.node.json" },
    { "path": "./tsconfig.web.json" }
  ]
}
```

Create `desktop/tsconfig.node.json`:

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
  "include": ["src/main/**/*", "src/preload/**/*", "electron.vite.config.ts"]
}
```

Create `desktop/tsconfig.web.json`:

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
  "include": ["src/renderer/**/*", "src/preload/types.ts"]
}
```

- [ ] **Step 1.4: Create electron-vite config**

Create `desktop/electron.vite.config.ts`:

```ts
import { defineConfig, externalizeDepsPlugin } from 'electron-vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { resolve } from 'node:path';

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: { outDir: 'out/main' },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: { outDir: 'out/preload' },
  },
  renderer: {
    root: resolve(__dirname, 'src/renderer'),
    plugins: [react(), tailwindcss()],
    build: {
      outDir: 'out/renderer',
      rollupOptions: { input: resolve(__dirname, 'src/renderer/index.html') },
    },
  },
});
```

- [ ] **Step 1.5: .gitignore + electron-builder placeholder**

Create `desktop/.gitignore`:

```
node_modules/
out/
dist/
*.tsbuildinfo
.DS_Store
```

Create `desktop/electron-builder.yml`:

```yaml
# Populated in Slice 5 — placeholder so CI knows where it'll live.
appId: app.ghostbrain.desktop
productName: ghostbrain
```

- [ ] **Step 1.6: Placeholder source files so dev boots**

Create `desktop/src/main/index.ts`:

```ts
import { app, BrowserWindow } from 'electron';
import { join } from 'node:path';

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 720,
    show: false,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: false,
    },
  });
  win.on('ready-to-show', () => win.show());
  if (process.env.ELECTRON_RENDERER_URL) {
    win.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'));
  }
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
```

Create `desktop/src/preload/index.ts`:

```ts
// Populated in Task 3 with the typed gb bridge. Empty for now.
export {};
```

Create `desktop/src/renderer/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>ghostbrain</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="./main.tsx"></script>
  </body>
</html>
```

Create `desktop/src/renderer/main.tsx`:

```tsx
import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';

const container = document.getElementById('root');
if (!container) throw new Error('root element missing');
createRoot(container).render(<App />);
```

Create `desktop/src/renderer/App.tsx`:

```tsx
export default function App() {
  return <div style={{ padding: 24, fontFamily: 'system-ui' }}>ghostbrain — booting…</div>;
}
```

- [ ] **Step 1.7: Install and run**

```bash
cd desktop
npm install
npm run dev
```

Expected: An Electron window opens showing "ghostbrain — booting…". Quit it.

- [ ] **Step 1.8: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): scaffold electron-vite project, archive prototype"
```

---

## Task 2: Window chrome — `hiddenInset` on Mac, native on Win

**Files:**
- Modify: `desktop/src/main/index.ts`

- [ ] **Step 2.1: Apply platform-specific titleBarStyle**

Replace `desktop/src/main/index.ts` with:

```ts
import { app, BrowserWindow } from 'electron';
import { join } from 'node:path';

function createWindow() {
  const isMac = process.platform === 'darwin';
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 720,
    show: false,
    backgroundColor: '#0E0F12',
    titleBarStyle: isMac ? 'hiddenInset' : 'default',
    trafficLightPosition: isMac ? { x: 14, y: 14 } : undefined,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: false,
    },
  });
  win.on('ready-to-show', () => win.show());
  if (process.env.ELECTRON_RENDERER_URL) {
    win.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'));
  }
}

app.whenReady().then(createWindow);
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
```

- [ ] **Step 2.2: Run dev, visually verify**

```bash
npm run dev
```

Expected on Mac: traffic lights sit ~14px from top-left, on top of the renderer area. Background is dark cool ink (#0E0F12) so no white flash. On Windows (verify later): standard titlebar with min/max/close on the right.

- [ ] **Step 2.3: Commit**

```bash
git add desktop/src/main/index.ts
git commit -m "feat(desktop): hiddenInset window chrome on macOS"
```

---

## Task 3: Typed preload bridge + electron-store settings

**Files:**
- Create: `desktop/src/preload/types.ts`
- Create: `desktop/src/main/settings.ts`
- Create: `desktop/src/main/dialogs.ts`
- Modify: `desktop/src/preload/index.ts`
- Modify: `desktop/src/main/index.ts`

- [ ] **Step 3.1: Define shared settings types**

Create `desktop/src/preload/types.ts`:

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
    set<K extends keyof Settings>(key: K, value: Settings[K]): Promise<void>;
  };
  dialogs: {
    pickVaultFolder(): Promise<string | null>;
  };
  shell: {
    openPath(path: string): Promise<string>;
  };
  platform: NodeJS.Platform;
}

declare global {
  interface Window {
    gb: GbBridge;
  }
}
```

- [ ] **Step 3.2: Implement main-side settings store**

Create `desktop/src/main/settings.ts`:

```ts
import Store from 'electron-store';
import { homedir } from 'node:os';
import { join } from 'node:path';
import type { Settings } from '../preload/types';

const defaults: Settings = {
  theme: 'dark',
  density: 'comfortable',
  vaultPath: join(homedir(), 'ghostbrain', 'vault'),
};

const store = new Store<Settings>({ name: 'config', defaults });

export function getAll(): Settings {
  return {
    theme: store.get('theme'),
    density: store.get('density'),
    vaultPath: store.get('vaultPath'),
  };
}

export function setKey<K extends keyof Settings>(key: K, value: Settings[K]): void {
  store.set(key, value);
}
```

- [ ] **Step 3.3: Implement folder picker**

Create `desktop/src/main/dialogs.ts`:

```ts
import { dialog, BrowserWindow } from 'electron';

export async function pickVaultFolder(): Promise<string | null> {
  const win = BrowserWindow.getFocusedWindow();
  const result = await dialog.showOpenDialog(win!, {
    title: 'Choose vault folder',
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths[0]!;
}
```

- [ ] **Step 3.4: Wire IPC handlers in main**

Replace `desktop/src/main/index.ts` with:

```ts
import { app, BrowserWindow, ipcMain, shell } from 'electron';
import { join } from 'node:path';
import * as settings from './settings';
import { pickVaultFolder } from './dialogs';
import type { Settings } from '../preload/types';

function createWindow() {
  const isMac = process.platform === 'darwin';
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 720,
    show: false,
    backgroundColor: '#0E0F12',
    titleBarStyle: isMac ? 'hiddenInset' : 'default',
    trafficLightPosition: isMac ? { x: 14, y: 14 } : undefined,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: false,
    },
  });
  win.on('ready-to-show', () => win.show());
  if (process.env.ELECTRON_RENDERER_URL) {
    win.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'));
  }
}

ipcMain.handle('gb:settings:getAll', () => settings.getAll());
ipcMain.handle(
  'gb:settings:set',
  (_e, key: keyof Settings, value: Settings[keyof Settings]) => {
    settings.setKey(key, value as never);
  },
);
ipcMain.handle('gb:dialogs:pickVaultFolder', () => pickVaultFolder());
ipcMain.handle('gb:shell:openPath', (_e, p: string) => shell.openPath(p));

app.whenReady().then(createWindow);
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
```

- [ ] **Step 3.5: Implement preload bridge**

Replace `desktop/src/preload/index.ts` with:

```ts
import { contextBridge, ipcRenderer } from 'electron';
import type { GbBridge, Settings } from './types';

const bridge: GbBridge = {
  settings: {
    getAll: () => ipcRenderer.invoke('gb:settings:getAll'),
    set: (key, value) => ipcRenderer.invoke('gb:settings:set', key, value),
  },
  dialogs: {
    pickVaultFolder: () => ipcRenderer.invoke('gb:dialogs:pickVaultFolder'),
  },
  shell: {
    openPath: (path: string) => ipcRenderer.invoke('gb:shell:openPath', path),
  },
  platform: process.platform,
};

contextBridge.exposeInMainWorld('gb', bridge);

// Re-export so Settings stays referenced (required by tsc for noUnusedLocals).
export type { Settings };
```

- [ ] **Step 3.6: Smoke-test the bridge in App.tsx**

Replace `desktop/src/renderer/App.tsx` with:

```tsx
import { useEffect, useState } from 'react';
import type { Settings } from '../preload/types';

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  useEffect(() => {
    window.gb.settings.getAll().then(setSettings);
  }, []);
  return (
    <div style={{ padding: 24, fontFamily: 'system-ui', color: 'white', background: '#0E0F12' }}>
      <h1>ghostbrain — bridge online</h1>
      <pre>{JSON.stringify(settings, null, 2)}</pre>
      <p>platform: {window.gb.platform}</p>
    </div>
  );
}
```

- [ ] **Step 3.7: Run dev and verify**

```bash
npm run dev
```

Expected: App displays the default settings JSON (`theme: "dark"`, `density: "comfortable"`, `vaultPath: "/Users/.../ghostbrain/vault"`) and the correct platform string.

- [ ] **Step 3.8: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): typed contextBridge + electron-store settings"
```

---

## Task 4: Tailwind v4 + design tokens + signature animations

**Files:**
- Create: `desktop/src/renderer/styles.css`
- Modify: `desktop/src/renderer/main.tsx`

- [ ] **Step 4.1: Author the Tailwind + tokens stylesheet**

Create `desktop/src/renderer/styles.css`:

```css
@import 'tailwindcss';

/* Bring in the design-system tokens that pre-existed the React port.
   colors_and_type.css owns CSS variables; @theme below promotes them
   to Tailwind utilities. */
@import '../../colors_and_type.css';

@font-face {
  font-family: 'Google Sans Flex';
  src: url('../../fonts/GoogleSansFlex-VariableFont_GRAD_ROND_opsz_slnt_wdth_wght.ttf')
    format('truetype-variations');
  font-weight: 100 1000;
  font-style: oblique -15deg 0deg;
  font-display: swap;
}

@theme {
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

  --font-display: 'Google Sans Flex', ui-sans-serif, system-ui, sans-serif;
  --font-body: 'Google Sans Flex', ui-sans-serif, system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;

  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;

  --shadow-card: 0 2px 4px rgba(0, 0, 0, 0.3), 0 12px 24px rgba(0, 0, 0, 0.45);
  --shadow-float: 0 16px 40px rgba(0, 0, 0, 0.55), 0 2px 6px rgba(0, 0, 0, 0.4);
}

html,
body,
#root {
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100%;
}

body {
  font-family: var(--font-body);
  background: #06070a;
  color: var(--ink-0);
  overflow: hidden;
  -webkit-font-smoothing: antialiased;
}

body[data-theme='light'] {
  background: #d8dbe0;
}

@keyframes gb-pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(255, 107, 90, 0.6);
  }
  70% {
    box-shadow: 0 0 0 8px rgba(255, 107, 90, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(255, 107, 90, 0);
  }
}
@keyframes gb-wave {
  from {
    transform: scaleY(0.4);
  }
  to {
    transform: scaleY(1);
  }
}
@keyframes gb-blink {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0;
  }
}
@keyframes gb-float {
  0%,
  100% {
    transform: translateY(-2px);
  }
  50% {
    transform: translateY(2px);
  }
}

.gb-floating {
  animation: gb-float 4s cubic-bezier(0.4, 0, 0.2, 1) infinite;
}

.gb-noise {
  position: relative;
  isolation: isolate;
}
.gb-noise::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 1;
  opacity: 0.04;
  mix-blend-mode: multiply;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='180' height='180'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>");
}

::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: var(--hairline-2);
  border-radius: 5px;
  border: 2px solid transparent;
  background-clip: padding-box;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--hairline-3);
  background-clip: padding-box;
  border: 2px solid transparent;
}
```

- [ ] **Step 4.2: Import styles in main.tsx**

Replace `desktop/src/renderer/main.tsx` with:

```tsx
import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

const container = document.getElementById('root');
if (!container) throw new Error('root element missing');
createRoot(container).render(<App />);
```

- [ ] **Step 4.3: Sanity-check tokens with App.tsx**

Replace `desktop/src/renderer/App.tsx` with:

```tsx
import { useEffect, useState } from 'react';
import type { Settings } from '../preload/types';

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  useEffect(() => {
    window.gb.settings.getAll().then(setSettings);
  }, []);
  return (
    <div className="bg-paper text-ink-0 p-6 h-full font-body">
      <h1 className="font-display text-4xl tracking-tight">ghostbrain</h1>
      <p className="text-ink-2 font-mono text-xs uppercase tracking-widest">tokens online</p>
      <pre className="bg-vellum text-ink-1 mt-4 rounded-md p-3 text-xs">
        {JSON.stringify(settings, null, 2)}
      </pre>
    </div>
  );
}
```

- [ ] **Step 4.4: Run dev and verify**

```bash
npm run dev
```

Expected: dark cool-ink background, lime-on-ink palette available; "ghostbrain" renders in the variable display font; the JSON box uses vellum.

- [ ] **Step 4.5: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): tailwind v4 with design-token @theme"
```

---

## Task 5: Vitest smoke test

**Files:**
- Create: `desktop/vitest.config.ts`
- Create: `desktop/src/renderer/test/setup.ts`
- Create: `desktop/src/renderer/__tests__/App.test.tsx`

- [ ] **Step 5.1: Vitest config**

Create `desktop/vitest.config.ts`:

```ts
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/renderer/test/setup.ts'],
    globals: true,
    include: ['src/renderer/**/*.test.{ts,tsx}'],
  },
});
```

- [ ] **Step 5.2: Test setup with bridge stub**

Create `desktop/src/renderer/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest';
import type { GbBridge, Settings } from '../../preload/types';

const defaultSettings: Settings = {
  theme: 'dark',
  density: 'comfortable',
  vaultPath: '/tmp/vault',
};

const stubBridge: GbBridge = {
  settings: {
    getAll: async () => ({ ...defaultSettings }),
    set: async () => {},
  },
  dialogs: { pickVaultFolder: async () => null },
  shell: { openPath: async () => '' },
  platform: 'darwin',
};

(globalThis as unknown as { window: Window & { gb: GbBridge } }).window.gb = stubBridge;
```

- [ ] **Step 5.3: Write smoke test**

Create `desktop/src/renderer/__tests__/App.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import App from '../App';

describe('App', () => {
  it('renders the brand without throwing', async () => {
    render(<App />);
    expect(await screen.findByText('ghostbrain')).toBeInTheDocument();
  });
});
```

- [ ] **Step 5.4: Run test**

```bash
cd desktop
npm test
```

Expected: 1 passed.

- [ ] **Step 5.5: Commit**

```bash
git add desktop/
git commit -m "test(desktop): vitest + RTL smoke test"
```

---

## Task 6: Zustand stores (navigation, settings, meeting, toast)

**Files:**
- Create: `desktop/src/renderer/stores/navigation.ts`
- Create: `desktop/src/renderer/stores/settings.ts`
- Create: `desktop/src/renderer/stores/meeting.ts`
- Create: `desktop/src/renderer/stores/toast.ts`
- Modify: `desktop/src/renderer/App.tsx`

- [ ] **Step 6.1: Navigation store**

Create `desktop/src/renderer/stores/navigation.ts`:

```ts
import { create } from 'zustand';

export type ScreenId = 'today' | 'connectors' | 'meetings' | 'capture' | 'vault' | 'settings';

interface NavState {
  active: ScreenId;
  setActive: (id: ScreenId) => void;
}

export const useNavigation = create<NavState>((set) => ({
  active: 'today',
  setActive: (id) => set({ active: id }),
}));
```

- [ ] **Step 6.2: Settings store with hydration + write-through**

Create `desktop/src/renderer/stores/settings.ts`:

```ts
import { create } from 'zustand';
import type { Settings } from '../../preload/types';

interface SettingsState extends Settings {
  ready: boolean;
  hydrate: () => Promise<void>;
  set: <K extends keyof Settings>(key: K, value: Settings[K]) => Promise<void>;
}

export const useSettings = create<SettingsState>((set) => ({
  theme: 'dark',
  density: 'comfortable',
  vaultPath: '',
  ready: false,
  hydrate: async () => {
    const all = await window.gb.settings.getAll();
    set({ ...all, ready: true });
  },
  set: async (key, value) => {
    await window.gb.settings.set(key, value);
    set({ [key]: value } as Pick<Settings, typeof key>);
  },
}));
```

- [ ] **Step 6.3: Meeting state machine**

Create `desktop/src/renderer/stores/meeting.ts`:

```ts
import { create } from 'zustand';

export type MeetingPhase = 'pre' | 'recording' | 'post';

interface MeetingState {
  phase: MeetingPhase;
  startedAt: number | null;
  start: () => void;
  stop: () => void;
  reset: () => void;
}

export const useMeeting = create<MeetingState>((set) => ({
  phase: 'pre',
  startedAt: null,
  start: () => set({ phase: 'recording', startedAt: Date.now() }),
  stop: () => set({ phase: 'post' }),
  reset: () => set({ phase: 'pre', startedAt: null }),
}));
```

- [ ] **Step 6.4: Toast store**

Create `desktop/src/renderer/stores/toast.ts`:

```ts
import { create } from 'zustand';

export interface Toast {
  id: number;
  message: string;
}

interface ToastState {
  toasts: Toast[];
  push: (message: string) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push: (message) => {
    const id = nextId++;
    set({ toasts: [...get().toasts, { id, message }] });
    setTimeout(() => get().dismiss(id), 3500);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));

export const stub = (slice: number) =>
  useToasts.getState().push(`wired in Slice ${slice}`);
```

- [ ] **Step 6.5: Hydrate settings + apply theme/density on the body**

Replace `desktop/src/renderer/App.tsx` with:

```tsx
import { useEffect } from 'react';
import { useSettings } from './stores/settings';

export default function App() {
  const { theme, density, ready, hydrate } = useSettings();

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  useEffect(() => {
    if (!ready) return;
    document.body.dataset.theme = theme;
    document.body.dataset.density = density;
  }, [theme, density, ready]);

  if (!ready) {
    return <div className="bg-paper text-ink-2 grid h-full place-items-center">…</div>;
  }
  return (
    <div className="bg-paper text-ink-0 h-full p-6 font-body">
      <h1 className="font-display text-4xl tracking-tight">ghostbrain</h1>
      <p className="text-ink-2 font-mono text-xs uppercase tracking-widest">stores online</p>
    </div>
  );
}
```

- [ ] **Step 6.6: Run dev and tests**

```bash
npm run dev   # quit after seeing it boots
npm test      # smoke test still passes
```

- [ ] **Step 6.7: Commit**

```bash
git add desktop/src/renderer/
git commit -m "feat(desktop): zustand stores (nav, settings, meeting, toast)"
```

---

## Task 7: Shared components — primitives

**Files:**
- Create: `desktop/src/renderer/components/Lucide.tsx`
- Create: `desktop/src/renderer/components/Ghost.tsx`
- Create: `desktop/src/renderer/components/Pill.tsx`
- Create: `desktop/src/renderer/components/Eyebrow.tsx`
- Create: `desktop/src/renderer/components/Btn.tsx`
- Create: `desktop/src/renderer/components/Toggle.tsx`
- Create: `desktop/src/renderer/components/Panel.tsx`

> All seven components are TypeScript ports of `desktop/_prototype/app-shell.jsx` and `desktop/_prototype/screens/today.jsx`. Convert inline `style={{...}}` to `React.CSSProperties` (don't migrate to Tailwind utilities — token-driven inline styles work fine and the design uses dynamic values like radial-gradient positions that don't map cleanly).

- [ ] **Step 7.1: Lucide icon component**

The chat transcript flagged that `lucide@latest` has no `toSvg`. Build the SVG safely with `createElementNS` (the prototype used `innerHTML`, but DOM-API construction is safer and just as fast).

```bash
cd desktop
npm install lucide
```

Create `desktop/src/renderer/components/Lucide.tsx`:

```tsx
import { useEffect, useRef } from 'react';
import * as lucide from 'lucide';

interface Props {
  name: string;
  size?: number;
  color?: string;
  style?: React.CSSProperties;
  className?: string;
}

const SVG_NS = 'http://www.w3.org/2000/svg';

export function Lucide({ name, size = 16, color, style, className }: Props) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const host = ref.current;
    if (!host) return;
    const camel = name.replace(/(^|-)(\w)/g, (_, __, c: string) =>
      c.toUpperCase(),
    ) as keyof typeof lucide.icons;
    const node = lucide.icons[camel] as
      | Array<[string, Record<string, string>]>
      | undefined;
    if (!Array.isArray(node)) return;

    while (host.firstChild) host.removeChild(host.firstChild);
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('width', String(size));
    svg.setAttribute('height', String(size));
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', color ?? 'currentColor');
    svg.setAttribute('stroke-width', '1.75');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    for (const [tag, attrs] of node) {
      const child = document.createElementNS(SVG_NS, tag);
      for (const [k, v] of Object.entries(attrs)) child.setAttribute(k, v);
      svg.appendChild(child);
    }
    host.appendChild(svg);
  }, [name, size, color]);

  return (
    <span
      ref={ref}
      className={className}
      style={{
        width: size,
        height: size,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        color: color ?? 'currentColor',
        ...style,
      }}
    />
  );
}
```

- [ ] **Step 7.2: Ghost glyph**

Create `desktop/src/renderer/components/Ghost.tsx`:

```tsx
interface Props {
  size?: number;
  color?: string;
  floating?: boolean;
}

export function Ghost({ size = 22, color = 'var(--neon)', floating = false }: Props) {
  return (
    <svg
      viewBox="0 0 100 110"
      style={{
        width: size,
        height: size * 1.1,
        flexShrink: 0,
        animation: floating ? 'gb-float 4s cubic-bezier(.4,0,.2,1) infinite' : 'none',
      }}
      aria-hidden="true"
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

- [ ] **Step 7.3: Pill, Eyebrow, Btn, Toggle, Panel**

Each of these is a 1:1 TypeScript port of the prototype components in `desktop/_prototype/app-shell.jsx` (Pill, Eyebrow, Btn) and `desktop/_prototype/screens/today.jsx` (Panel) and `desktop/_prototype/screens/connectors.jsx` (Toggle). Concrete code for each is in the spec — use the original JSX as the reference, convert prop signatures to TS interfaces, drop default-export style and use named exports, replace `style={{}}` JSX with typed `React.CSSProperties`. No behavioral changes.

For agents executing this plan: read each prototype component, copy its body into the corresponding `.tsx` file, type the props. The visual output should match exactly. Total time ~10 minutes for all five.

- [ ] **Step 7.4: Type-check**

```bash
cd desktop && npm run typecheck
```

Expected: no errors.

- [ ] **Step 7.5: Commit**

```bash
git add desktop/src/renderer/components/ desktop/package.json desktop/package-lock.json
git commit -m "feat(desktop): port shared primitives (Lucide, Ghost, Btn, Pill, Toggle, Panel, Eyebrow)"
```

---

## Task 8: Shared chrome — Sidebar, TopBar, StatusBar, WindowChrome, Toaster

**Files:**
- Create: `desktop/src/renderer/lib/platform.ts`
- Create: `desktop/src/renderer/components/WindowChrome.tsx`
- Create: `desktop/src/renderer/components/Sidebar.tsx`
- Create: `desktop/src/renderer/components/TopBar.tsx`
- Create: `desktop/src/renderer/components/StatusBar.tsx`
- Create: `desktop/src/renderer/components/Toaster.tsx`
- Modify: `desktop/src/renderer/App.tsx`

- [ ] **Step 8.1: Platform helper**

Create `desktop/src/renderer/lib/platform.ts`:

```ts
export const isMac = window.gb.platform === 'darwin';
```

- [ ] **Step 8.2: WindowChrome (no fake border-radius — real OS chrome handles it)**

Create `desktop/src/renderer/components/WindowChrome.tsx`:

```tsx
interface Props {
  children: React.ReactNode;
}

export function WindowChrome({ children }: Props) {
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        background: 'var(--bg-paper)',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
      }}
    >
      {children}
    </div>
  );
}
```

- [ ] **Step 8.3: Sidebar with platform-aware traffic-light spacer**

Create `desktop/src/renderer/components/Sidebar.tsx`. This is a TS port of the prototype `Sidebar`/`NavRow`/`VaultRow`/`RecordingDot` components in `desktop/_prototype/app-shell.jsx`, with these explicit changes:

1. Drop the prototype's hand-drawn `TRAFFIC` lights cluster — Mac uses real OS lights via `hiddenInset`. Replace it with a 36px-tall spacer that's only rendered when `isMac` is true (gives the real traffic lights room to overlay).
2. Active screen comes from `useNavigation()`, recording phase from `useMeeting()`.
3. Whole `<aside>` is a drag region; `<nav>` and the footer reset to no-drag for clickability.
4. Vault footer shows `~/ghostbrain/vault` (real path, not the design's `~/Obsidian/brain`).

Skeleton:

```tsx
import { useState } from 'react';
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
      style={{
        width: 8, height: 8, borderRadius: '50%',
        background: 'var(--oxblood)',
        boxShadow: '0 0 0 0 rgba(255,107,90,0.6)',
        animation: 'gb-pulse 1.4s ease-out infinite',
      }}
    />
  );
}

export function Sidebar() {
  const { active, setActive } = useNavigation();
  const phase = useMeeting((s) => s.phase);
  return (
    <aside
      style={{
        width: 220, flexShrink: 0,
        background: 'var(--bg-paper)',
        borderRight: '1px solid var(--hairline)',
        display: 'flex', flexDirection: 'column',
        WebkitAppRegion: 'drag',
      } as React.CSSProperties}
    >
      {isMac && <div style={{ height: 36, flexShrink: 0 }} />}
      {/* brand block, nav, vault folders, footer — port from prototype */}
      {/* … (see _prototype/app-shell.jsx for the inner JSX of each block) */}
    </aside>
  );
}

// NavRow and VaultRow: port unchanged from prototype.
```

The agent should fill in the brand/nav/footer sections by porting from `desktop/_prototype/app-shell.jsx` lines ~155–253 (excluding the `TRAFFIC` cluster and changing the vault path string).

- [ ] **Step 8.4: TopBar (1:1 TS port of prototype `TopBar`)**

Create `desktop/src/renderer/components/TopBar.tsx`:

```tsx
interface Props {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}

export function TopBar({ title, subtitle, right }: Props) {
  return (
    <div
      style={{
        height: 56, padding: '0 24px',
        borderBottom: '1px solid var(--hairline)',
        display: 'flex', alignItems: 'center', gap: 16,
        background: 'var(--bg-paper)',
        flexShrink: 0,
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, lineHeight: 1.15 }}>
        <h1 style={{
          margin: 0, fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 600,
          color: 'var(--ink-0)', letterSpacing: '-0.02em',
        }}>{title}</h1>
        {subtitle && (
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--ink-2)',
            textTransform: 'uppercase', letterSpacing: '0.12em',
          }}>{subtitle}</span>
        )}
      </div>
      <div style={{ flex: 1 }} />
      {right}
    </div>
  );
}
```

- [ ] **Step 8.5: StatusBar (port from prototype `StatusBar` in app.jsx, read recording phase from store)**

Create `desktop/src/renderer/components/StatusBar.tsx` — port the prototype `StatusBar` body, replace `recordingState === 'recording'` with `phase === 'recording'` from `useMeeting`. The "6 connectors live", "2,489 indexed", "last sync 1m ago" strings stay as stub copy in Slice 1 (Slice 3 wires them).

- [ ] **Step 8.6: Toaster**

Create `desktop/src/renderer/components/Toaster.tsx`:

```tsx
import { useToasts } from '../stores/toast';

export function Toaster() {
  const toasts = useToasts((s) => s.toasts);
  return (
    <div
      style={{
        position: 'fixed', bottom: 40, right: 20,
        display: 'flex', flexDirection: 'column', gap: 8,
        zIndex: 1000, pointerEvents: 'none',
      }}
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          style={{
            background: 'var(--bg-vellum)',
            border: '1px solid var(--hairline-2)',
            borderRadius: 8, padding: '10px 14px',
            color: 'var(--ink-0)', fontSize: 12,
            fontFamily: 'var(--font-mono)',
            boxShadow: 'var(--shadow-card)',
          }}
        >
          {t.message}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 8.7: Wire shell in App.tsx with placeholders**

Replace `desktop/src/renderer/App.tsx` with:

```tsx
import { useEffect } from 'react';
import { useSettings } from './stores/settings';
import { useNavigation } from './stores/navigation';
import { WindowChrome } from './components/WindowChrome';
import { Sidebar } from './components/Sidebar';
import { StatusBar } from './components/StatusBar';
import { Toaster } from './components/Toaster';

function ScreenStub({ name }: { name: string }) {
  return (
    <div style={{
      flex: 1, display: 'grid', placeItems: 'center',
      color: 'var(--ink-2)', fontFamily: 'var(--font-mono)', fontSize: 14,
    }}>
      {name} screen — coming next
    </div>
  );
}

export default function App() {
  const { theme, density, ready, hydrate } = useSettings();
  const active = useNavigation((s) => s.active);

  useEffect(() => { hydrate(); }, [hydrate]);
  useEffect(() => {
    if (!ready) return;
    document.body.dataset.theme = theme;
    document.body.dataset.density = density;
  }, [theme, density, ready]);

  if (!ready) {
    return <div className="bg-paper text-ink-2 grid h-full place-items-center">…</div>;
  }
  return (
    <WindowChrome>
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar />
        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <ScreenStub name={active} />
        </main>
      </div>
      <StatusBar />
      <Toaster />
    </WindowChrome>
  );
}
```

- [ ] **Step 8.8: Run dev, verify nav works, traffic lights overlay cleanly**

```bash
npm run dev
```

Expected: Sidebar with brand, six clickable nav items, status bar, real Mac traffic lights at top-left of the sidebar without overlapping the brand block.

- [ ] **Step 8.9: Commit**

```bash
git add desktop/src/renderer/
git commit -m "feat(desktop): sidebar nav, top bar, status bar, toaster shell"
```

---

## Task 9: Mock data per screen

**Files:**
- Create: `desktop/src/renderer/lib/mocks/today.ts`
- Create: `desktop/src/renderer/lib/mocks/connectors.ts`
- Create: `desktop/src/renderer/lib/mocks/meetings.ts`
- Create: `desktop/src/renderer/lib/mocks/capture.ts`

> All four files extract the inline data arrays from the prototype. Slice 3 will replace these files (not edit them) with real data from the Python sidecar.

- [ ] **Step 9.1: Today mock**

Create `desktop/src/renderer/lib/mocks/today.ts`:

```ts
export interface AgendaItem {
  time: string; dur: string; title: string; with: string[];
  status: 'upcoming' | 'recorded';
}
export interface ActivityRow {
  source: string; verb: string; subject: string; time: string;
}
export interface ConnectorPulse {
  name: string; state: 'on' | 'off' | 'err'; count: string;
}
export interface CaptureLatelyItem {
  source: string; title: string; snippet: string; from: string;
}
export interface Suggestion {
  icon: string; title: string; body: string; accent?: boolean;
}

export const AGENDA: AgendaItem[] = [
  { time: '11:00', dur: '30m', title: 'Design crit · onboarding v3', with: ['mira', 'jules', 'sam'], status: 'upcoming' },
  { time: '14:30', dur: '60m', title: 'Weekly with Theo', with: ['theo'], status: 'upcoming' },
  { time: '09:00', dur: '20m', title: 'standup', with: ['team'], status: 'recorded' },
];

export const ACTIVITY: ActivityRow[] = [
  { source: 'gmail', verb: 'archived', subject: '3 newsletters', time: '2m' },
  { source: 'slack', verb: 'captured', subject: '#design-crit thread', time: '5m' },
  { source: 'linear', verb: 'linked', subject: 'GHO-241 → meeting notes', time: '14m' },
  { source: 'notion', verb: 'watching', subject: 'Q2 roadmap', time: '22m' },
  { source: 'calendar', verb: 'indexed', subject: '3 events', time: '38m' },
  { source: 'gmail', verb: 'extracted', subject: 'action item from theo', time: '1h' },
];

export const CONNECTOR_PULSES: ConnectorPulse[] = [
  { name: 'gmail', state: 'on', count: '14.8k' },
  { name: 'slack', state: 'on', count: '9.4k' },
  { name: 'notion', state: 'on', count: '1.1k' },
  { name: 'linear', state: 'on', count: '824' },
  { name: 'calendar', state: 'on', count: '412' },
  { name: 'github', state: 'err', count: '—' },
  { name: 'drive', state: 'off', count: '—' },
];

export const CAUGHT_LATELY: CaptureLatelyItem[] = [
  { source: 'gmail', title: 're: design crit moved', snippet: 'works for me — moving the 11am to thursday next week.', from: 'theo · 8:14am' },
  { source: 'slack', title: '#product-feedback', snippet: 'users keep asking for keyboard shortcuts on the meetings view. ranked it as p1.', from: 'mira · 8:01am' },
  { source: 'linear', title: 'GHO-241 closed', snippet: 'recording auto-pause when system sleeps. shipped in 1.4.2.', from: 'jules · 7:48am' },
];

export const SUGGESTIONS: Suggestion[] = [
  { icon: 'link', title: 'connect drive', body: '3 mentions of shared docs in slack this week — none are indexed.' },
  { icon: 'user-plus', title: 'follow up with @sam', body: 'last reply from sam was 9 days ago. on a thread you starred.' },
  { icon: 'sparkles', title: 'weekly digest is ready', body: 'summary of 24 captured threads, ready to drop into your daily note.', accent: true },
];

export const STATS = {
  captured:  { label: 'captured',  value: '241',   delta: '+38 vs yest' },
  meetings:  { label: 'meetings',  value: '2',     delta: 'next in 23m' },
  followups: { label: 'followups', value: '8',     delta: '3 overdue' },
  vaultSize: { label: 'vault size',value: '2,489', delta: 'notes' },
};
```

- [ ] **Step 9.2: Connectors mock**

Create `desktop/src/renderer/lib/mocks/connectors.ts` by porting the `CONNECTORS` array from `desktop/_prototype/screens/connectors.jsx` lines 3–18 verbatim. Add an exported `Connector` interface matching the shape, and an exported `ConnectorState = 'on' | 'err' | 'off'` type.

- [ ] **Step 9.3: Meetings mock**

Create `desktop/src/renderer/lib/mocks/meetings.ts` by porting `PARTICIPANTS` (lines 3–8), the `transcript` array from `ActiveRecording` (lines 175–183), `HISTORY` (lines 358–364), and the `[34, 28, 22, 16]` airtime array as `SPEAKER_AIRTIME`. Type each as `Participant`, `TranscriptLine`, `PastMeeting`.

- [ ] **Step 9.4: Capture mock**

Create `desktop/src/renderer/lib/mocks/capture.ts` by porting `CAPTURE_ITEMS` from `desktop/_prototype/screens/capture-settings.jsx` lines 4–13 verbatim. Type as `CaptureRecord[]`.

- [ ] **Step 9.5: Type-check + commit**

```bash
npm run typecheck
git add desktop/src/renderer/lib/
git commit -m "feat(desktop): typed mock data per screen"
```

---

## Task 10: Today screen

**Files:**
- Create: `desktop/src/renderer/screens/today.tsx`
- Modify: `desktop/src/renderer/App.tsx`

- [ ] **Step 10.1: Port the Today screen**

Create `desktop/src/renderer/screens/today.tsx`. This is a TypeScript port of `desktop/_prototype/screens/today.jsx`, with these explicit changes:

1. Take no props — read `setActive` from `useNavigation()` directly.
2. Replace inline data arrays (`AGENDA`, `ACTIVITY`, etc.) with imports from `../lib/mocks/today`.
3. Replace `Stat`, `AgendaItem`, `ActivityRow`, `ConnectorPulse`, `CaptureItem`, `Suggestion` sub-components with TS-typed versions, kept inside the same file (they're not reused elsewhere).
4. "ask the archive" button → `onClick={() => stub(3)}` from `../stores/toast`. "start recording" button → `setActive('meetings')`.
5. Asset paths: connector svgs are bundled under `/assets/connectors/` — verify they resolve at dev time. (Move `desktop/assets/` into `desktop/src/renderer/assets/` if Vite can't reach the top-level assets dir; see Step 10.2.)

Wrapper:

```tsx
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { Eyebrow } from '../components/Eyebrow';
import { Panel } from '../components/Panel';
import { useNavigation } from '../stores/navigation';
import { stub } from '../stores/toast';
import {
  AGENDA, ACTIVITY, CONNECTOR_PULSES, CAUGHT_LATELY, SUGGESTIONS, STATS,
  type AgendaItem as AgendaItemT,
  type ActivityRow as ActivityRowT,
  type ConnectorPulse as ConnectorPulseT,
  type CaptureLatelyItem,
  type Suggestion as SuggestionT,
} from '../lib/mocks/today';

export function TodayScreen() {
  const setActive = useNavigation((s) => s.setActive);
  return (
    <div style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-paper)' }}>
      <TopBar
        title="today"
        subtitle="thursday · may 8"
        right={
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="ghost" size="sm" icon={<Lucide name="search" size={14} />} onClick={() => stub(3)}>
              ask…
              <kbd style={{ marginLeft: 8, fontFamily: 'var(--font-mono)', fontSize: 9, padding: '1px 5px', borderRadius: 3, background: 'var(--bg-fog)', color: 'var(--ink-2)' }}>⌘K</kbd>
            </Btn>
            <Btn variant="secondary" size="sm" icon={<Lucide name="bell" size={14} />} onClick={() => stub(3)} />
          </div>
        }
      />
      {/* …port body from _prototype/screens/today.jsx lines 17–131 */}
      {/* with the data sources swapped to imports above and CTAs swapped to `onClick={() => stub(3)}` */}
      {/* (or `setActive(...)` for nav-only buttons) */}
    </div>
  );
}

// Sub-components (Stat, AgendaItem, ActivityRow, ConnectorPulse, CaptureItem, Suggestion):
// port from _prototype/screens/today.jsx lines 134–249 with TS interfaces matching the mock types.
```

- [ ] **Step 10.2: Make connector SVGs reachable from the renderer**

Move `desktop/assets/` and `desktop/fonts/` so Vite can serve them as static files. Vite serves `public/` from the renderer root automatically.

```bash
cd desktop
mkdir -p src/renderer/public
mv assets src/renderer/public/assets
mv fonts src/renderer/public/fonts
```

Then update `desktop/src/renderer/styles.css` font-face URL:

```css
@font-face {
  font-family: 'Google Sans Flex';
  src: url('/fonts/GoogleSansFlex-VariableFont_GRAD_ROND_opsz_slnt_wdth_wght.ttf')
    format('truetype-variations');
  font-weight: 100 1000;
  font-style: oblique -15deg 0deg;
  font-display: swap;
}
```

And in any code that referenced `assets/connectors/<x>.svg`, prefix with `/`:

```tsx
<img src={`/assets/connectors/${name}.svg`} />
```

Also update `colors_and_type.css` (root) — the `gb-noise` data-URL is fine, but the `@font-face` block in that file is now duplicated by `styles.css`. Remove the `@font-face` from `colors_and_type.css` to avoid the resolver looking for a `fonts/` sibling.

- [ ] **Step 10.3: Wire the Today screen into App.tsx**

Modify `desktop/src/renderer/App.tsx` — replace `ScreenStub` with a switch:

```tsx
import { TodayScreen } from './screens/today';
// …

{active === 'today' && <TodayScreen />}
{active !== 'today' && <ScreenStub name={active} />}
```

- [ ] **Step 10.4: Run dev, navigate to Today, verify layout matches prototype**

```bash
npm run dev
```

Open the app, click Today (it's the default). Compare visually to `desktop/_prototype/index.html` (open the prototype in a separate browser tab via `python3 -m http.server` from `desktop/_prototype/` for side-by-side reference).

Expected: Hero greeting with neon-highlighted "ghostbrain caught", 4-stat grid, agenda + activity panels, 7-cell connector pulse strip with logos, caught-lately + suggestions row.

- [ ] **Step 10.5: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): today screen — dashboard, agenda, activity, suggestions"
```

---

## Task 11: Connectors screen

**Files:**
- Create: `desktop/src/renderer/screens/connectors.tsx`
- Modify: `desktop/src/renderer/App.tsx`

- [ ] **Step 11.1: Port Connectors screen**

Create `desktop/src/renderer/screens/connectors.tsx`. TS port of `desktop/_prototype/screens/connectors.jsx`. Specific changes:

1. Take no props.
2. Move `CONNECTORS` import to `../lib/mocks/connectors`.
3. Local state: `selectedId` (default first connector's id), `filter` (`'all' | ConnectorState`).
4. All action buttons (`sync all`, `add connector`, `connect`, `reauthorize`, `sync now`, `pause`, `disconnect`) call `stub(3)`.
5. The existing prototype `Toggle` is now imported from `../components/Toggle` — make sure its props match.
6. `DetailBlock` stays inside this file (only used here).

Wrapper:

```tsx
import { useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { Eyebrow } from '../components/Eyebrow';
import { Toggle } from '../components/Toggle';
import { CONNECTORS, type Connector, type ConnectorState } from '../lib/mocks/connectors';
import { stub } from '../stores/toast';

type Filter = 'all' | ConnectorState;

export function ConnectorsScreen() {
  const [selectedId, setSelectedId] = useState<string>(CONNECTORS[0]!.id);
  const [filter, setFilter] = useState<Filter>('all');
  const filtered = CONNECTORS.filter((c) => filter === 'all' || c.state === filter);
  const selected = CONNECTORS.find((c) => c.id === selectedId)!;

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg-paper)' }}>
      <TopBar
        title="connectors"
        subtitle="6 of 7 · syncing live"
        right={
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="secondary" size="sm" icon={<Lucide name="refresh-cw" size={13} />} onClick={() => stub(3)}>sync all</Btn>
            <Btn variant="primary" size="sm" icon={<Lucide name="plus" size={13} color="#0E0F12" />} onClick={() => stub(3)}>add connector</Btn>
          </div>
        }
      />
      {/* port body from _prototype/screens/connectors.jsx lines 37–80, then the */}
      {/* ConnectorRow/AddConnectorRow/ConnectorDetail/DetailBlock components (lines 84–250) */}
    </div>
  );
}
```

- [ ] **Step 11.2: Mount in App.tsx, switch case for connectors**

```tsx
import { ConnectorsScreen } from './screens/connectors';
// …
{active === 'connectors' && <ConnectorsScreen />}
```

- [ ] **Step 11.3: Run dev, click Connectors, verify**

Expected: List of 7 connectors with status pills, filter chips (`all/connected/error/disconnected`), detail panel on the right showing scopes, vault destination, filters with toggles. Click a row → detail updates. Click a filter → list narrows.

- [ ] **Step 11.4: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): connectors screen — list + detail"
```

---

## Task 12: Meetings screen (pre / live / post + history)

**Files:**
- Create: `desktop/src/renderer/screens/meetings.tsx`
- Create: `desktop/src/renderer/lib/format.ts`
- Modify: `desktop/src/renderer/App.tsx`

- [ ] **Step 12.1: Time formatting helper**

Create `desktop/src/renderer/lib/format.ts`:

```ts
export function mmss(seconds: number): string {
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}
```

- [ ] **Step 12.2: Port Meetings screen with real state machine**

Create `desktop/src/renderer/screens/meetings.tsx`. TS port of `desktop/_prototype/screens/meetings.jsx`. Changes:

1. `recordingState` is now `useMeeting().phase`. Start/stop/pause buttons call `useMeeting().start/stop/reset`.
2. `elapsed` in `ActiveRecording` derives from `useMeeting().startedAt` via a `setInterval` that updates a local `elapsed` count every 1s. Use `mmss(elapsed)` from the format helper.
3. The transcript and participants come from `../lib/mocks/meetings`.
4. "import recording", "audio", "open meet", "configure…", "save to vault", "share md", "play audio" CTAs → `stub(4)`.
5. The prototype's hardcoded `recordingState === 'recording'` checks become `phase === 'recording'`.

Wrapper:

```tsx
import { useEffect, useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Pill } from '../components/Pill';
import { Eyebrow } from '../components/Eyebrow';
import { Panel } from '../components/Panel';
import { useMeeting } from '../stores/meeting';
import { stub } from '../stores/toast';
import { PARTICIPANTS, TRANSCRIPT, HISTORY, SPEAKER_AIRTIME } from '../lib/mocks/meetings';
import { mmss } from '../lib/format';

export function MeetingsScreen() {
  const { phase, startedAt, start, stop, reset } = useMeeting();
  return (
    <div style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-paper)' }}>
      <TopBar
        title="meetings"
        subtitle={phase === 'recording' ? '· recording in progress' : '47 in vault · 2 today'}
        right={
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn variant="ghost" size="sm" icon={<Lucide name="settings-2" size={13} />} onClick={() => stub(4)}>audio</Btn>
            <Btn variant="secondary" size="sm" icon={<Lucide name="upload" size={13} />} onClick={() => stub(4)}>import recording</Btn>
          </div>
        }
      />
      {phase === 'pre' && <PreMeeting onStart={start} />}
      {phase === 'recording' && <ActiveRecording startedAt={startedAt!} onStop={stop} />}
      {phase === 'post' && <PostMeeting onClose={reset} />}
      <MeetingHistory />
    </div>
  );
}

function ActiveRecording({ startedAt, onStop }: { startedAt: number; onStop: () => void }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const tick = () => setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [startedAt]);
  // …port body from _prototype/screens/meetings.jsx lines 184–275
  // Replace `{mm}:{ss}` with `{mmss(elapsed)}`
  return /* … */;
}

// PreMeeting, PostMeeting, MeetingHistory: port from _prototype/screens/meetings.jsx
// (lines 33–109, 289–339, 366–391). Sub-components ParticipantRow, AudioSource,
// Waveform, Catch, Action, SmallStat: port from same file.
```

- [ ] **Step 12.3: Mount + switch in App.tsx**

```tsx
import { MeetingsScreen } from './screens/meetings';
// …
{active === 'meetings' && <MeetingsScreen />}
```

- [ ] **Step 12.4: Verify state machine works**

```bash
npm run dev
```

Click Meetings → Pre. Click "start recording" → flips to Live, timer starts at 00:00, recording dot in sidebar pulses, status bar shows "recording". Click "stop" → flips to Post. Click X (close) → back to Pre.

- [ ] **Step 12.5: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): meetings screen with pre/live/post state machine"
```

---

## Task 13: Capture screen

**Files:**
- Create: `desktop/src/renderer/screens/capture.tsx`
- Modify: `desktop/src/renderer/App.tsx`

- [ ] **Step 13.1: Port Capture screen**

Create `desktop/src/renderer/screens/capture.tsx`. TS port of the `CaptureScreen` portion of `desktop/_prototype/screens/capture-settings.jsx` (lines 1–122, plus its `Catch` sub-component). Changes:

1. `CAPTURE_ITEMS` import from `../lib/mocks/capture`.
2. Default selection = first item id; filter = `'all'`.
3. Action buttons (`mark all read`, `filters`, archive, mute thread, save to vault) → `stub(3)`.
4. The prototype reuses a `Catch` component already in `meetings.jsx`; for the capture screen, define a local copy of `Catch` inside `capture.tsx` (or extract to `components/Catch.tsx` if you prefer — both screens use it; extracting is fine).

Recommend extracting `Catch` to `desktop/src/renderer/components/Catch.tsx` for DRY:

```tsx
import { Lucide } from './Lucide';

interface Props { icon: string; text: string; }

export function Catch({ icon, text }: Props) {
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 8,
      padding: '8px 6px', borderRadius: 4,
      fontSize: 12, color: 'var(--ink-0)', lineHeight: 1.4,
    }}>
      <Lucide name={icon} size={12} color="var(--neon)" style={{ marginTop: 3 }} />
      <span>{text}</span>
    </div>
  );
}
```

If extracted, also import it in `meetings.tsx` (replace its inline `Catch`).

- [ ] **Step 13.2: Mount + switch in App.tsx**

```tsx
import { CaptureScreen } from './screens/capture';
// …
{active === 'capture' && <CaptureScreen />}
```

- [ ] **Step 13.3: Verify, commit**

```bash
npm run dev   # click Capture, verify list + detail panel render
git add desktop/
git commit -m "feat(desktop): capture inbox screen"
```

---

## Task 14: Vault screen with real `shell.openPath`

**Files:**
- Create: `desktop/src/renderer/screens/vault.tsx`
- Modify: `desktop/src/renderer/App.tsx`

- [ ] **Step 14.1: Port Vault placeholder, wire real openPath**

Create `desktop/src/renderer/screens/vault.tsx`:

```tsx
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Ghost } from '../components/Ghost';
import { useSettings } from '../stores/settings';

export function VaultScreen() {
  const vaultPath = useSettings((s) => s.vaultPath);
  const onOpen = () => {
    window.gb.shell.openPath(vaultPath);
  };
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: 'var(--bg-paper)' }}>
      <TopBar title="vault" subtitle="opens in your file manager" />
      <div style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 18, padding: 48,
      }}>
        <Ghost size={72} floating />
        <h2 style={{
          margin: 0, fontFamily: 'var(--font-display)', fontSize: 28,
          fontWeight: 600, letterSpacing: '-0.025em', color: 'var(--ink-0)',
        }}>
          your vault is on disk.
        </h2>
        <p style={{
          margin: 0, fontSize: 14, color: 'var(--ink-2)', textAlign: 'center', maxWidth: 380,
        }}>
          ghostbrain doesn't replace your editor — it feeds the vault. open it to see everything as markdown.
        </p>
        <Btn
          variant="primary"
          size="lg"
          icon={<Lucide name="external-link" size={14} color="#0E0F12" />}
          onClick={onOpen}
        >
          open vault folder
        </Btn>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--ink-3)' }}>
          {vaultPath}
        </span>
      </div>
    </div>
  );
}
```

> Note: copy is changed from "open in obsidian" to "open vault folder" — Slice 1 doesn't ship with an Obsidian dependency. Switching to Obsidian-specific deep linking is a Slice 3 concern (post-real-data) once we know the user has Obsidian installed.

- [ ] **Step 14.2: Mount + switch**

```tsx
import { VaultScreen } from './screens/vault';
// …
{active === 'vault' && <VaultScreen />}
```

- [ ] **Step 14.3: Verify and commit**

```bash
npm run dev
# Click Vault. Click "open vault folder". The Finder/Explorer should open the path.
# (If the path doesn't exist yet, the dialog will surface that — Slice 3 will create it.)
git add desktop/
git commit -m "feat(desktop): vault screen with real shell.openPath"
```

---

## Task 15: Settings screen — replaces tweaks panel

**Files:**
- Create: `desktop/src/renderer/lib/shortcuts.ts`
- Create: `desktop/src/renderer/screens/settings.tsx`
- Modify: `desktop/src/renderer/App.tsx`

- [ ] **Step 15.1: Platform-aware shortcut formatter**

Create `desktop/src/renderer/lib/shortcuts.ts`:

```ts
import { isMac } from './platform';

export interface Shortcut { mod: 'cmd-shift' | 'ctrl-shift'; key: string; }

export function format(s: Shortcut): string {
  const prefix = isMac ? '⌘ ⇧' : 'Ctrl ⇧';
  return `${prefix} ${s.key}`;
}

export const HOTKEYS: Array<{ label: string; shortcut: Shortcut }> = [
  { label: 'ask the archive',         shortcut: { mod: 'cmd-shift', key: 'K' } },
  { label: 'quick capture',           shortcut: { mod: 'cmd-shift', key: 'C' } },
  { label: 'start recording',         shortcut: { mod: 'cmd-shift', key: 'R' } },
  { label: 'stop recording',          shortcut: { mod: 'cmd-shift', key: 'S' } },
  { label: 'open vault',              shortcut: { mod: 'cmd-shift', key: 'V' } },
  { label: 'toggle ghostbrain window',shortcut: { mod: 'cmd-shift', key: 'G' } },
];
```

- [ ] **Step 15.2: Port Settings screen with real wiring**

Create `desktop/src/renderer/screens/settings.tsx`. TS port of the `SettingsScreen` portion of `desktop/_prototype/screens/capture-settings.jsx` (lines 124–263). Changes:

1. **Add a Display section** (was a tweak): theme + density segmented controls. Make it the first section in the nav (before vault).
2. **Vault path picker (real)**: clicking "change" calls `window.gb.dialogs.pickVaultFolder()`; if non-null, calls `useSettings.set('vaultPath', path)`.
3. **Theme** ↔ `useSettings.set('theme', v)`.
4. **Density** ↔ `useSettings.set('density', v)`.
5. **Hotkeys** rendered via `format(shortcut)` from `lib/shortcuts.ts`.
6. All other toggles, selects, account/about → `stub(3)` for actions, value-only for displays. Specifically: `cloud sync`, `e2e`, `telemetry`, `LLM provider`, `auto-record`, `diarize`, `extract action items`, `audio retention`, `transcript model`, `manage plan`, `view all devices`, `sign out`, `change folder structure`, `daily note`, `markdown frontmatter`, `auto-link mentions`.

Skeleton:

```tsx
import { useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Btn } from '../components/Btn';
import { Lucide } from '../components/Lucide';
import { Toggle } from '../components/Toggle';
import { Pill } from '../components/Pill';
import { Ghost } from '../components/Ghost';
import { useSettings } from '../stores/settings';
import { stub } from '../stores/toast';
import { HOTKEYS, format as formatShortcut } from '../lib/shortcuts';

type SectionId = 'display' | 'vault' | 'privacy' | 'meeting' | 'hotkeys' | 'account' | 'about';

const SECTIONS: Array<{ id: SectionId; label: string; icon: string }> = [
  { id: 'display', label: 'display',  icon: 'sun' },
  { id: 'vault',   label: 'vault',    icon: 'hard-drive' },
  { id: 'privacy', label: 'privacy',  icon: 'shield' },
  { id: 'meeting', label: 'meetings', icon: 'mic' },
  { id: 'hotkeys', label: 'hotkeys',  icon: 'command' },
  { id: 'account', label: 'account',  icon: 'user' },
  { id: 'about',   label: 'about',    icon: 'info' },
];

export function SettingsScreen() {
  const [section, setSection] = useState<SectionId>('display');
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg-paper)' }}>
      <TopBar title="settings" subtitle="ghostbrain v 0.1.0" />
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '200px 1fr', overflow: 'hidden' }}>
        <nav style={{ borderRight: '1px solid var(--hairline)', padding: '16px 8px', overflowY: 'auto' }}>
          {SECTIONS.map((s) => (
            <SectionRow key={s.id} {...s} active={section === s.id} onClick={() => setSection(s.id)} />
          ))}
        </nav>
        <div style={{ overflowY: 'auto', padding: '24px 32px', maxWidth: 720 }}>
          {section === 'display' && <DisplaySettings />}
          {section === 'vault'   && <VaultSettings />}
          {section === 'privacy' && <PrivacySettings />}
          {section === 'meeting' && <MeetingSettings />}
          {section === 'hotkeys' && <HotkeySettings />}
          {section === 'account' && <AccountSettings />}
          {section === 'about'   && <AboutSettings />}
        </div>
      </div>
    </div>
  );
}

function DisplaySettings() {
  const { theme, density, set } = useSettings();
  return (
    <div>
      <SectionHeader title="display" sub="how ghostbrain looks." />
      <SettingRow
        label="theme"
        sub="cool ink (dark) or cool bone (light)"
        control={
          <Segmented
            value={theme}
            options={[{ value: 'dark', label: 'dark' }, { value: 'light', label: 'light' }]}
            onChange={(v) => set('theme', v as 'dark' | 'light')}
          />
        }
      />
      <SettingRow
        label="density"
        sub="layout breathing room"
        control={
          <Segmented
            value={density}
            options={[{ value: 'comfortable', label: 'comfy' }, { value: 'compact', label: 'compact' }]}
            onChange={(v) => set('density', v as 'comfortable' | 'compact')}
          />
        }
      />
    </div>
  );
}

function VaultSettings() {
  const { vaultPath, set } = useSettings();
  const onPick = async () => {
    const next = await window.gb.dialogs.pickVaultFolder();
    if (next) await set('vaultPath', next);
  };
  return (
    <div>
      <SectionHeader title="vault" sub="where ghostbrain writes everything it catches." />
      <SettingRow
        label="vault path"
        sub={vaultPath}
        control={<Btn variant="secondary" size="sm" icon={<Lucide name="folder-open" size={13} />} onClick={onPick}>change</Btn>}
      />
      <SettingRow label="folder structure" sub="how ghostbrain organizes captured items"
        control={<select style={selectStyle} onChange={() => stub(3)}><option>by source</option><option>by date</option><option>by person</option></select>} />
      <SettingRow label="daily note" sub="capture digest appended to today's daily note" control={<Toggle on />} />
      <SettingRow label="markdown frontmatter" sub="add yaml metadata to every captured file" control={<Toggle on />} />
      <SettingRow label="auto-link mentions" sub='turn @names and #tags into [[wikilinks]]' control={<Toggle on />} />
    </div>
  );
}

// PrivacySettings, MeetingSettings, AccountSettings, AboutSettings:
// port from _prototype/screens/capture-settings.jsx lines 194–262 with toggles
// rendered as <Toggle on={…} /> (no onChange wiring in Slice 1 — Slice 3).

function HotkeySettings() {
  return (
    <div>
      <SectionHeader title="hotkeys" sub="global shortcuts — work even when ghostbrain isn't focused." />
      {HOTKEYS.map((h) => (
        <SettingRow
          key={h.label}
          label={h.label}
          control={
            <kbd style={{
              fontFamily: 'var(--font-mono)', fontSize: 11, padding: '4px 10px',
              borderRadius: 4, background: 'var(--bg-vellum)',
              border: '1px solid var(--hairline-2)', color: 'var(--ink-0)',
            }}>{formatShortcut(h.shortcut)}</kbd>
          }
        />
      ))}
    </div>
  );
}

// SettingRow, SectionHeader, SectionRow, Segmented helpers below — small, port from prototype
// or write fresh per the wrapper signatures referenced above.

const selectStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)', fontSize: 11,
  padding: '6px 10px', borderRadius: 4,
  background: 'var(--bg-vellum)', color: 'var(--ink-0)',
  border: '1px solid var(--hairline-2)', cursor: 'pointer',
};
```

The agent should fill in the helpers (`SettingRow`, `SectionHeader`, `SectionRow`, `Segmented`) — these are tiny:

```tsx
function SettingRow({ label, sub, control }: { label: string; sub?: string; control: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '14px 0', borderBottom: '1px solid var(--hairline)' }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, color: 'var(--ink-0)', fontWeight: 500 }}>{label}</div>
        {sub && <div style={{ fontSize: 11, color: 'var(--ink-2)', marginTop: 2, lineHeight: 1.4 }}>{sub}</div>}
      </div>
      <div>{control}</div>
    </div>
  );
}

function SectionHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <header style={{ marginBottom: 16 }}>
      <h2 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 26, fontWeight: 600, color: 'var(--ink-0)', letterSpacing: '-0.025em' }}>{title}</h2>
      {sub && <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--ink-2)' }}>{sub}</p>}
    </header>
  );
}

function SectionRow({ id, label, icon, active, onClick }: {
  id: SectionId; label: string; icon: string; active: boolean; onClick: () => void;
}) {
  return (
    <div onClick={onClick} style={{
      display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 6,
      cursor: 'pointer',
      background: active ? 'var(--bg-vellum)' : 'transparent',
      fontSize: 13, color: active ? 'var(--ink-0)' : 'var(--ink-1)',
      fontWeight: active ? 500 : 400, marginBottom: 2,
    }}>
      <Lucide name={icon} size={14} color={active ? 'var(--neon)' : 'var(--ink-2)'} />
      {label}
    </div>
  );
}

function Segmented<T extends string>({ value, options, onChange }: {
  value: T; options: Array<{ value: T; label: string }>; onChange: (v: T) => void;
}) {
  return (
    <div style={{
      display: 'inline-flex', padding: 2, borderRadius: 6,
      background: 'var(--bg-vellum)', border: '1px solid var(--hairline-2)',
    }}>
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          style={{
            padding: '6px 12px', borderRadius: 4, border: 'none', cursor: 'pointer',
            background: value === o.value ? 'rgba(197,255,61,0.16)' : 'transparent',
            color: value === o.value ? 'var(--neon)' : 'var(--ink-1)',
            fontFamily: 'var(--font-mono)', fontSize: 11,
          }}
        >{o.label}</button>
      ))}
    </div>
  );
}
```

- [ ] **Step 15.3: Mount + switch**

```tsx
import { SettingsScreen } from './screens/settings';
// …
{active === 'settings' && <SettingsScreen />}
```

- [ ] **Step 15.4: Verify settings persist**

```bash
npm run dev
```

Open Settings → Display. Switch theme to light. Quit the app. Re-launch → still light. Switch back to dark. Quit. Re-launch → dark. Same for density and vault path.

- [ ] **Step 15.5: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): settings screen with persistent display/vault settings"
```

---

## Task 16: ESLint + Prettier configs and CI

**Files:**
- Create: `desktop/.eslintrc.cjs`
- Create: `desktop/.prettierrc`
- Create: `desktop/.prettierignore`
- Modify: `desktop/package.json` (already has lint script)

- [ ] **Step 16.1: Prettier config**

Create `desktop/.prettierrc`:

```json
{
  "singleQuote": true,
  "semi": true,
  "trailingComma": "all",
  "printWidth": 100,
  "tabWidth": 2,
  "arrowParens": "always"
}
```

Create `desktop/.prettierignore`:

```
node_modules/
out/
dist/
src/renderer/public/
_prototype/
```

- [ ] **Step 16.2: ESLint config**

Create `desktop/.eslintrc.cjs`:

```js
module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  parserOptions: { ecmaVersion: 2022, sourceType: 'module', ecmaFeatures: { jsx: true } },
  plugins: ['@typescript-eslint', 'react', 'react-hooks'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react/recommended',
    'plugin:react-hooks/recommended',
  ],
  settings: { react: { version: '18' } },
  rules: {
    'react/react-in-jsx-scope': 'off',
    'react/prop-types': 'off',
    '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    '@typescript-eslint/no-non-null-assertion': 'off',
  },
  ignorePatterns: ['out/', 'dist/', 'node_modules/', '_prototype/', 'src/renderer/public/'],
};
```

- [ ] **Step 16.3: Run lint, fix issues**

```bash
cd desktop
npm run lint
```

Fix any violations until lint passes with zero warnings.

- [ ] **Step 16.4: Format**

```bash
npm run format
```

- [ ] **Step 16.5: Commit**

```bash
git add desktop/
git commit -m "chore(desktop): eslint + prettier configs"
```

---

## Task 17: Final verification — delete prototype, README, end-to-end smoke

**Files:**
- Delete: `desktop/_prototype/`
- Create: `desktop/README.md`

- [ ] **Step 17.1: Visual parity check (last chance with the prototype)**

```bash
# In one terminal:
cd desktop && npm run dev

# In another:
cd desktop/_prototype && python3 -m http.server 8765
# Open http://localhost:8765 — compare screen-by-screen.
```

Walk through all 6 screens in both. Fix any visual delta you spot before deleting the reference. Rerun until parity is achieved.

- [ ] **Step 17.2: Delete the prototype**

```bash
rm -rf desktop/_prototype
```

- [ ] **Step 17.3: Add a minimal README so the next engineer can run it**

Create `desktop/README.md`:

```markdown
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
```

- [ ] **Step 17.4: Final checks**

```bash
cd desktop
npm run typecheck   # passes
npm run lint        # zero warnings
npm test            # 1 passed
npm run dev         # all 6 screens render, settings persist, toasts appear for stubs
```

- [ ] **Step 17.5: Commit**

```bash
git add desktop/
git commit -m "feat(desktop): finalize Slice 1 — drop prototype, add README"
```

---

## Self-review

This plan is checked against `docs/superpowers/specs/2026-05-08-desktop-shell-slice-1-design.md`:

| Spec section | Tasks | Notes |
|--------------|-------|-------|
| Stack (Electron, electron-vite, React, TS, Tailwind v4, Zustand, electron-store, Vitest, ESLint, Prettier) | 1, 4, 5, 6, 16 | All covered |
| Repo layout | 1 | Files match the file-table at the top |
| Window chrome (`hiddenInset` Mac, native Win) | 2 | + sidebar spacer in Task 8 |
| State management (3 stores + toast) | 6 | Toast added as a 4th store for stub policy |
| Settings persistence (electron-store + typed bridge) | 3, 6 | `getAll()` and typed `set<K>` |
| Replacing tweaks panel (theme, density, screen, recording, showNoise) | 6, 8, 12, 15 | `showNoise` dropped per spec |
| Mock data extraction | 9 | One file per screen |
| Connector list reconciliation (option i) | 9, 11 | Mock list kept; data-driven so Slice 3 only changes data |
| Stub policy for actions | 6 (toast helper), 10–15 (each screen) | `stub(N)` helper used everywhere it matters |
| Tests (smoke only) | 5, 16 | App-renders smoke test + tsc + ESLint as stand-ins |
| Cross-platform considerations (fonts, menus, ⌘/Ctrl) | 4, 15 | `lib/shortcuts.ts` switches modifier per platform |
| Acceptance criteria 1–10 | 17 | Final verification step covers all 10 |

**Placeholder check:** No "TBD"/"TODO". Every task has runnable commands and file paths. The only "port from prototype lines X–Y" references are exact line numbers in files that the agent has on disk during implementation (under `desktop/_prototype/`). The prototype is deleted only as the very last step (17.2) after parity is verified.

**Type consistency:** `Settings`, `ScreenId`, `MeetingPhase`, `Connector`, `ConnectorState`, `Toast`, `Shortcut` — each defined exactly once and referenced consistently. `useSettings.set<K>(key, value)` matches the bridge `window.gb.settings.set<K>(key, value)`.

**Scope:** The plan stays inside Slice 1's bounds (no Python, no real audio, no installer). Buttons that would call backend wire to `stub(N)` toasts that name the slice owning them.
