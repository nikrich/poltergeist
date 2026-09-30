# Script Writer — Slice 1 (Writing Tool) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an installable Poltergeist plugin, `script-writer`. It's a screenplay editor that formats a live page as you type, paginates to industry standard, keeps a script library of vault notes, and exports PDF and Fountain. The AI co-writer is slice 2 and is not in this plan.

**Architecture:**
- A plain-Fountain source of truth is edited in CodeMirror 6. One pure parser (`src/fountain/parse.js`) drives the editor line decorations, the scene and character navigators, the paginator, and export.
- A pure paginator produces positioned lines. One HTML renderer feeds both the in-app page view and the PDF, which the main process prints through a hidden `BrowserWindow`.
- Scripts are vault notes written with `PUT /v1/notes`. A debounced saver retries with backoff and mirrors unsaved text to the plugin data dir.

**Tech Stack:** Plain ESM JavaScript + JSX, React 18, CodeMirror 6 (`@codemirror/state|view|commands|autocomplete`), esbuild, vitest (+ jsdom for one smoke test), `@fontsource/courier-prime`.

**Spec:** `docs/superpowers/specs/2026-09-30-script-writer-plugin-design.md`. Read it first. This plan implements §1–4, §6 (minus FDX), §7–9, and slice 1 of §10.

## Global Constraints

- **Plugin location and manifest.** The plugin lives at `plugins/script-writer/`. Manifest:
  - `id` `script-writer` (`^[a-z][a-z0-9-]{1,31}$`), `apiVersion` literally `1`, `icon` `clapperboard`.
  - `entry.main` `dist/main.cjs`, `entry.renderer` `dist/renderer.mjs`.
- **`dist/` is committed.** The app never builds plugins.
- **Renderer backend calls go through `plugin.sidecar.request(method, path, body)`.** It resolves to `{ok: true, data}` or `{ok: false, error, status?}` and never throws for HTTP errors. Only `/v1/*` paths are used.
- **IPC channels match `^[a-z0-9:_-]+$`, and each is registered once.** Handler args are exactly the args given to `plugin.ipc.invoke(channel, ...args)`. Everything crossing IPC is plain JSON.
- **Mutable plugin files go only under `ctx.dataDir`,** never `pluginDir`.
- **Script path is `20-contexts/<context>/projects/<project-slug>/<script-slug>.screenplay.md`.** Frontmatter `type: screenplay` plus the title-page keys `title, credit, author, source, draft_date, contact, scene_numbers, updated`. The body is raw Fountain.
- **Projects and contexts come from `GET /v1/projects` and `GET /v1/vault/contexts`, and new projects from `POST /v1/projects {context, name}`** (409 means it already exists). Contexts are never hard-coded.
- **Page geometry:**
  - Courier 12pt at 10 chars/inch and 6 lines/inch.
  - Margins: top 1", bottom 1", left 1.5", right 1". **54 body lines per page.** The page number sits top-right at 0.5" from page 2 onward.
- **Column geometry, in chars from the text left:**
  - Action: x 0, width 60.
  - Character: x 22.
  - Parenthetical: x 16, width 25.
  - Dialogue: x 10, width 35.
  - Transition: right-aligned to col 60.
- **Autosave** fires 1.5s after the last keystroke, plus on unmount, editor blur, and Cmd+S. **Retry backoff** is 2s, 4s, 8s, 16s, then 30s (capped).
- **Style with `plugin.theme` variables** (`--paper --vellum --fog --hairline --ink-0 --ink-1 --ink-2 --neon --oxblood`) with fallbacks. The script sheet is always paper white with black Courier in paper mode.
- **All commands run from the worktree `/Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer`,** on branch `feat/script-writer`. Plugin commands run from `plugins/script-writer/` inside it: `cd` there with an absolute path in every Bash call and check `git branch --show-current` before committing.

## Review Focus

1. **Backend down or restarting while typing.** Text must never be lost: the saver keeps retrying, mirrors to the data dir, and the next open offers a restore. Tests: Task 9 (`saver.test.js` failure cases and `shouldOfferDraft`).
2. **Long scripts (120–150 pages, about 10k lines).** Parsing on every keystroke must stay fast. Test: Task 2 perf test (10k lines parse in under 200ms).
3. **Imported Fountain with CRLF, a title page, or a first line like `FADE IN:`.** The title page must map to metadata and the body must not be swallowed. Tests: Task 3 (`fromFountain` cases).
4. **A dialogue or action block longer than a full page.** The paginator must not loop forever or drop or duplicate lines, and every page stays at 54 lines or fewer. Test: Task 4 (oversized-block invariants).
5. **Creating a script whose slug already exists in the vault or registry.** An existing file must never be overwritten; the new script takes `-2`, `-3`, and so on. Test: Task 3 (`freeScriptPath`).

---

## File Structure

```
plugins/script-writer/
  manifest.json                 package.json   build.mjs   vitest.config.js   README.md
  src/main.js                   # activate/deactivate: IPC handlers (drafts, import/export, pdf)
  src/main/drafts.js            # dataDir/drafts/<key>.json read/write/clear
  src/main/files.js             # export names, import limits, font inlining for PDF html
  src/renderer.jsx              # mount(el, plugin) → React root
  src/fountain/parse.js         # Fountain → Element[]
  src/fountain/document.js      # frontmatter ⇄ meta, Fountain title page, slugs, paths
  src/fountain/outline.js       # scenes(), characters(), cueName(), moveScene()
  src/paginate/wrap.js          # visibleLength(), wrap()
  src/paginate/paginate.js      # paginate() → Page[]
  src/render/pageHtml.js        # inlineHtml, renderPage, renderTitlePage, pageCss, fontFaceCss, documentHtml
  src/api/backend.js            # readScript, writeScript, listProjects, listContexts, createProject
  src/store/registry.js         # library registry in plugin settings
  src/store/saver.js            # debounced save + retry + mirror; shouldOfferDraft
  src/editor/analysis.js        # analysisField (parse per doc change)
  src/editor/hints.js           # hintField/setHint/hintAt (typed-element hints for empty lines)
  src/editor/flow.js            # pure element-flow rules: CYCLE, NEXT_ON_ENTER, applyType, markerRanges…
  src/editor/commands.js        # typeAt, cycleType, setType, enter (state-only CM commands)
  src/editor/completions.js     # pure completionsFor(), locations()
  src/editor/complete.js        # CM autocompletion source
  src/editor/decorations.js     # line classes + marker marks
  src/editor/autocaps.js        # uppercase typing on caps elements
  src/editor/focus.js           # focus mode (dim + typewriter scroll)
  src/editor/keymap.js          # Tab/Shift-Tab/Enter/Shift-Enter/Mod-1..7/Mod-s/Mod-Shift-f
  src/editor/setup.js           # createEditor(), setFocusMode()
  src/ui/styles.js              # appCss()
  src/ui/App.jsx  Library.jsx  NewScriptDialog.jsx  TitlePageFields.jsx
  src/ui/EditorScreen.jsx  SceneNav.jsx  CharacterList.jsx  PageView.jsx  useUiSettings.js
  src/**/__tests__/*.test.js(x)
  dist/                         # committed build output (main.cjs, renderer.mjs, fonts/)
```

Element line numbers are **0-based** source-line indexes. CodeMirror lines are **1-based**, so convert with `+1`/`-1` at the editor boundary only.

---

### Task 1: Scaffold the plugin (manifest, build, test harness)

**Files:**
- Create: `plugins/script-writer/manifest.json`, `package.json`, `build.mjs`, `vitest.config.js`, `src/main.js`, `src/renderer.jsx`
- Test: `plugins/script-writer/src/__tests__/manifest.test.js`

**Interfaces:**
- Produces: `npm test` and `npm run build` in `plugins/script-writer/`. `dist/fonts/courier-prime-latin-{400,700}-{normal,italic}.woff2` plus `dist/fonts/OFL.txt`.

- [ ] **Step 1: Carry the spec in (already done in this worktree) and create the directory**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && mkdir -p plugins/script-writer/src/__tests__
```
Expected: `feat/script-writer`

- [ ] **Step 2: Write `manifest.json`, `package.json`, `vitest.config.js`**

`plugins/script-writer/manifest.json`:
```json
{
  "id": "script-writer",
  "name": "Script Writer",
  "version": "0.1.0",
  "description": "Write industry-standard screenplays in Fountain with a live formatted page, exact pagination, PDF export, and your vault projects on hand.",
  "apiVersion": 1,
  "icon": "clapperboard",
  "entry": { "main": "dist/main.cjs", "renderer": "dist/renderer.mjs" }
}
```

`plugins/script-writer/package.json`:
```json
{
  "name": "poltergeist-plugin-script-writer",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "node build.mjs",
    "test": "vitest run"
  },
  "dependencies": {
    "@codemirror/autocomplete": "^6.20.3",
    "@codemirror/commands": "^6.11.1",
    "@codemirror/state": "^6.7.6",
    "@codemirror/view": "^6.43.13",
    "@fontsource/courier-prime": "^5.3.0",
    "lucide-react": "^1.14.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "esbuild": "^0.21.0",
    "jsdom": "^25.0.0",
    "vitest": "^1.6.0"
  }
}
```

`plugins/script-writer/vitest.config.js`:
```js
import { defineConfig } from 'vitest/config';

export default defineConfig({
  esbuild: { jsx: 'automatic' },
  test: { include: ['src/**/__tests__/**/*.test.{js,jsx}'], environment: 'node' },
});
```

- [ ] **Step 3: Write the failing manifest test**

`plugins/script-writer/src/__tests__/manifest.test.js`:
```js
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const manifest = JSON.parse(readFileSync(new URL('../../manifest.json', import.meta.url), 'utf-8'));

describe('manifest', () => {
  it('satisfies the app manifest contract', () => {
    expect(manifest.id).toMatch(/^[a-z][a-z0-9-]{1,31}$/);
    expect(manifest.name.length).toBeGreaterThan(0);
    expect(manifest.name.length).toBeLessThanOrEqual(64);
    expect(manifest.apiVersion).toBe(1);
    expect(manifest.icon).toMatch(/^[a-z0-9-]+$/);
    expect(manifest.entry.main).toMatch(/\.cjs$/);
    expect(manifest.entry.renderer).toMatch(/\.mjs$/);
    expect(manifest.description.length).toBeLessThanOrEqual(500);
  });
});
```

- [ ] **Step 4: Install and run the test**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npm install && npx vitest run src/__tests__/manifest.test.js
```
Expected: PASS (1 test). The manifest already exists, so this test guards regressions. That's fine for a scaffold task.

- [ ] **Step 5: Write the stub entries and `build.mjs`**

`plugins/script-writer/src/main.js`:
```js
// Main-process entry. Task 10 replaces this stub with the IPC handlers.
export function activate(ctx) {
  ctx.log('script-writer activated');
}

export function deactivate() {}
```

`plugins/script-writer/src/renderer.jsx`:
```jsx
// Renderer entry. Task 11 replaces this stub with the React app.
export function mount(el) {
  el.textContent = 'Script Writer';
  return () => { el.textContent = ''; };
}
```

`plugins/script-writer/build.mjs`:
```js
import { build } from 'esbuild';
import { copyFileSync, mkdirSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

await build({
  entryPoints: ['src/main.js'],
  outfile: 'dist/main.cjs',
  bundle: true,
  platform: 'node',
  format: 'cjs',
  external: ['electron'],
});

await build({
  entryPoints: ['src/renderer.jsx'],
  outfile: 'dist/renderer.mjs',
  bundle: true,
  platform: 'browser',
  format: 'esm',
  jsx: 'automatic',
  minify: true,
  define: { 'process.env.NODE_ENV': '"production"' },
});

// Courier Prime (SIL OFL) ships inside dist so the page view and the PDF use
// the real screenplay face. The renderer loads it via new URL('./fonts/', import.meta.url).
const fontSrc = 'node_modules/@fontsource/courier-prime/files';
const fonts = readdirSync(fontSrc).filter((f) => /^courier-prime-latin-(400|700)-(normal|italic)\.woff2$/.test(f));
if (fonts.length !== 4) throw new Error(`expected 4 Courier Prime woff2 files in ${fontSrc}, found ${fonts.length}`);
mkdirSync('dist/fonts', { recursive: true });
for (const f of fonts) copyFileSync(join(fontSrc, f), join('dist/fonts', f));
copyFileSync('node_modules/@fontsource/courier-prime/LICENSE', 'dist/fonts/OFL.txt');
console.log('built dist/main.cjs + dist/renderer.mjs + dist/fonts');
```

- [ ] **Step 6: Build**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npm run build && ls dist dist/fonts
```
Expected: `main.cjs renderer.mjs fonts`, then 4 woff2 files and `OFL.txt`. If `LICENSE` is missing from the package, run `ls node_modules/@fontsource/courier-prime` and copy whichever license file is there (it may be `LICENSE.md` or `OFL.txt`), then update `build.mjs` to match.

- [ ] **Step 7: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer && git commit -m "feat(script-writer): scaffold plugin (manifest, build, test harness)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Fountain parser

**Files:**
- Create: `plugins/script-writer/src/fountain/parse.js`
- Test: `plugins/script-writer/src/fountain/__tests__/parse.test.js`

**Interfaces:**
- Produces:
  - `parse(text: string) → Element[]`, where `Element = {type, text, line, lineEnd, sceneNumber?, dual?: 'left'|'right', depth?}` and `line`/`lineEnd` are 0-based.
  - `type ∈ scene_heading | action | character | parenthetical | dialogue | transition | centered | lyric | page_break | section | synopsis | note | boneyard`.
  - `text` has forcing markers (`. ! @ > < ~ = #`), scene numbers, and the `^` removed. Emphasis markers are kept.
  - `SCENE_PREFIX: RegExp` and `isUpperCue(t: string) → boolean`.

- [ ] **Step 1: Write the failing tests**

`plugins/script-writer/src/fountain/__tests__/parse.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { parse, isUpperCue } from '../parse.js';

const types = (s) => parse(s).map((e) => e.type);

describe('parse', () => {
  it('parses a scene heading, action, and a dialogue block', () => {
    const els = parse('INT. LIGHTHOUSE - NIGHT\n\nRain hammers the glass.\n\nMARA\n(quietly)\nIt found us.\nAgain.\n');
    expect(els.map((e) => e.type)).toEqual(['scene_heading', 'action', 'character', 'parenthetical', 'dialogue']);
    expect(els[0]).toMatchObject({ text: 'INT. LIGHTHOUSE - NIGHT', line: 0, lineEnd: 0 });
    expect(els[4]).toMatchObject({ text: 'It found us.\nAgain.', line: 6, lineEnd: 7 });
  });

  it('recognises all scene prefixes case-insensitively and forced headings', () => {
    expect(types('ext. beach - day')).toEqual(['scene_heading']);
    expect(types('INT./EXT. CAR - MOVING')).toEqual(['scene_heading']);
    expect(types('I/E. HALLWAY')).toEqual(['scene_heading']);
    expect(parse('.FLASHBACK')[0]).toMatchObject({ type: 'scene_heading', text: 'FLASHBACK' });
    expect(types('..not a heading')).toEqual(['action']);
  });

  it('extracts scene numbers', () => {
    expect(parse('INT. HOUSE - DAY #12A#')[0]).toMatchObject({ text: 'INT. HOUSE - DAY', sceneNumber: '12A' });
  });

  it('accepts a scene heading with no blank line after it', () => {
    expect(types('INT. HOUSE - DAY\nMara enters.')).toEqual(['scene_heading', 'action']);
  });

  it('treats an all-caps line followed by a blank as action, not a character', () => {
    expect(types('BANG!\n\nThe door explodes.')).toEqual(['action', 'action']);
  });

  it('treats an all-caps line followed by text as a character cue', () => {
    expect(types('BANG!\nThe door explodes.')).toEqual(['character', 'dialogue']);
  });

  it('keeps character extensions and handles forced/lowercase-extension cues', () => {
    expect(parse('MARA (V.O.)\nHello.')[0]).toMatchObject({ type: 'character', text: 'MARA (V.O.)' });
    expect(parse("MARA (cont'd)\nHello.")[0].type).toBe('character');
    expect(parse('@McCLANE\nYippee.')[0]).toMatchObject({ type: 'character', text: 'McCLANE' });
  });

  it('parses transitions: auto TO: and forced >', () => {
    expect(types('Action.\n\nCUT TO:\n\nINT. X - DAY')).toEqual(['action', 'transition', 'scene_heading']);
    expect(parse('> FADE OUT.')[0]).toMatchObject({ type: 'transition', text: 'FADE OUT.' });
    expect(types('Action.\n\nSMASH CUT TO:\nMore action.')).toEqual(['action', 'character', 'dialogue']);
  });

  it('parses centered, lyric, page break, section, synopsis, note and boneyard', () => {
    const els = parse('>THE END<\n\n~Sing it\n\n===\n\n## Act Two\n\n= She finds the key.\n\n[[fix this]]\n\n/* old\nscene */');
    expect(els.map((e) => e.type)).toEqual(['centered', 'lyric', 'page_break', 'section', 'synopsis', 'note', 'boneyard']);
    expect(els[0].text).toBe('THE END');
    expect(els[3]).toMatchObject({ text: 'Act Two', depth: 2 });
    expect(els[4].text).toBe('She finds the key.');
    expect(els[5].text).toBe('fix this');
    expect(els[6]).toMatchObject({ line: 12, lineEnd: 13 });
  });

  it('strips forced-action markers', () => {
    expect(parse('!SCREAMS FROM BELOW\nMore.')[0]).toMatchObject({ type: 'action', text: 'SCREAMS FROM BELOW\nMore.' });
  });

  it('marks dual dialogue', () => {
    const els = parse('BRICK\nScrew retirement.\n\nSTEEL ^\nScrew retirement.');
    expect(els[0]).toMatchObject({ type: 'character', dual: 'left' });
    expect(els[2]).toMatchObject({ type: 'character', text: 'STEEL', dual: 'right' });
  });

  it('keeps two-space lines inside dialogue', () => {
    const els = parse('MARA\nLine one.\n  \nLine two.');
    expect(els.map((e) => e.type)).toEqual(['character', 'dialogue']);
    expect(els[1].lineEnd).toBe(3);
  });

  it('normalises CRLF', () => {
    expect(types('INT. A - DAY\r\n\r\nAction.')).toEqual(['scene_heading', 'action']);
  });

  it('parses a 10k-line script quickly', () => {
    const block = 'INT. ROOM - DAY\n\nShe waits by the window, counting.\n\nMARA\n(beat)\nNot yet.\n\n';
    const big = block.repeat(1250); // 10,000 lines
    const t0 = performance.now();
    const els = parse(big);
    expect(performance.now() - t0).toBeLessThan(200);
    expect(els.length).toBe(1250 * 5);
  });
});

describe('isUpperCue', () => {
  it('ignores the parenthetical extension and dual marker', () => {
    expect(isUpperCue("MARA (cont'd)")).toBe(true);
    expect(isUpperCue('MARA ^')).toBe(true);
    expect(isUpperCue('Mara')).toBe(false);
    expect(isUpperCue('123')).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/fountain
```
Expected: FAIL, "Failed to resolve import ../parse.js".

- [ ] **Step 3: Implement `parse.js`**

`plugins/script-writer/src/fountain/parse.js`:
```js
// Fountain 1.1 parser → flat element list. `line`/`lineEnd` are 0-based
// indexes into the source split on \n. Pure — shared by the editor
// decorations, navigators, paginator and export.

export const SCENE_PREFIX = /^(?:INT\.?\/EXT|EXT\.?\/INT|INT\/EXT|I\/E|INT|EXT|EST)(?:\.|\s)/i;
const SCENE_NUMBER = /\s*#([A-Za-z0-9.-]+)#\s*$/;

const blank = (s) => s === undefined || s.trim() === '';

/** A cue has letters and none lowercase outside its (extension). */
export function isUpperCue(t) {
  const name = t.replace(/\s*\^\s*$/, '').replace(/\([^)]*\)/g, '').trim();
  return /[A-Z]/.test(name) && !/[a-z]/.test(name);
}

function sceneHeading(t, line) {
  const raw = t.startsWith('.') ? t.slice(1).trim() : t;
  const el = { type: 'scene_heading', text: raw, line, lineEnd: line };
  const m = raw.match(SCENE_NUMBER);
  if (m) {
    el.sceneNumber = m[1];
    el.text = raw.slice(0, m.index).trim();
  }
  return el;
}

function readDialogue(lines, i, out) {
  let cue = lines[i].trim();
  if (cue.startsWith('@')) cue = cue.slice(1).trim();
  const charEl = { type: 'character', text: cue, line: i, lineEnd: i };
  if (/\^\s*$/.test(cue)) {
    charEl.text = cue.replace(/\s*\^\s*$/, '');
    charEl.dual = 'right';
    for (let k = out.length - 1; k >= 0; k--) {
      const t = out[k].type;
      if (t === 'character') { out[k].dual = 'left'; break; }
      if (t !== 'dialogue' && t !== 'parenthetical') break;
    }
  }
  out.push(charEl);
  i++;
  let cur = null;
  while (i < lines.length && (!blank(lines[i]) || /^ {2,}$/.test(lines[i]))) {
    const t = lines[i].trim();
    if (/^\(.*\)$/.test(t)) {
      cur = null;
      out.push({ type: 'parenthetical', text: t, line: i, lineEnd: i });
    } else if (cur) {
      cur.text += `\n${t}`;
      cur.lineEnd = i;
    } else {
      cur = { type: 'dialogue', text: t, line: i, lineEnd: i };
      out.push(cur);
    }
    i++;
  }
  return i;
}

export function parse(text) {
  const lines = String(text ?? '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const t = lines[i].trim();
    if (t === '') { i++; continue; }
    const prevBlank = blank(lines[i - 1]);
    const nextBlank = blank(lines[i + 1]);
    const single = (type, txt, extra = {}) => {
      out.push({ type, text: txt, line: i, lineEnd: i, ...extra });
      i++;
    };

    if (t.startsWith('/*')) {
      const start = i;
      while (i < lines.length - 1 && !lines[i].includes('*/')) i++;
      out.push({ type: 'boneyard', text: lines.slice(start, i + 1).join('\n'), line: start, lineEnd: i });
      i++;
      continue;
    }
    if (/^={3,}$/.test(t)) { single('page_break', ''); continue; }
    if (t.startsWith('#')) {
      const m = t.match(/^(#+)\s*(.*)$/);
      single('section', m[2], { depth: m[1].length });
      continue;
    }
    if (t.startsWith('=')) { single('synopsis', t.slice(1).trim()); continue; }
    if (/^\[\[[\s\S]*\]\]$/.test(t)) { single('note', t.slice(2, -2).trim()); continue; }
    if (t.startsWith('~')) { single('lyric', t.slice(1).trim()); continue; }
    if (t.startsWith('>') && t.endsWith('<')) { single('centered', t.slice(1, -1).trim()); continue; }
    if (t.startsWith('>')) { single('transition', t.slice(1).trim()); continue; }
    if (prevBlank && ((t.startsWith('.') && !t.startsWith('..')) || SCENE_PREFIX.test(t))) {
      out.push(sceneHeading(t, i));
      i++;
      continue;
    }
    if (prevBlank && nextBlank && t.endsWith('TO:') && t === t.toUpperCase()) { single('transition', t); continue; }
    if (prevBlank && !nextBlank && (t.startsWith('@') || (!t.startsWith('!') && isUpperCue(t)))) {
      i = readDialogue(lines, i, out);
      continue;
    }
    // Action paragraph: runs to the next blank line; each source line is a hard break.
    const start = i;
    const buf = [];
    while (i < lines.length && !blank(lines[i])) {
      const s = lines[i].trim();
      buf.push(s.startsWith('!') ? s.slice(1) : s);
      i++;
    }
    out.push({ type: 'action', text: buf.join('\n'), line: start, lineEnd: i - 1 });
  }
  return out;
}
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/fountain
```
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer/src/fountain && git commit -m "feat(script-writer): Fountain parser

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Document model and backend client

**Files:**
- Create: `plugins/script-writer/src/fountain/document.js`, `plugins/script-writer/src/api/backend.js`
- Test: `plugins/script-writer/src/fountain/__tests__/document.test.js`, `plugins/script-writer/src/api/__tests__/backend.test.js`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces from `document.js`:
  - `DEFAULT_META` and `normalizeMeta(fm) → Meta`. `Meta = {title, credit, author, source, draft_date, contact, scene_numbers: boolean, updated}`; all fields except `scene_numbers` are strings.
  - `serializeFile(meta, body) → string` and `toFountain(meta, body) → string`.
  - `fromFountain(text) → {meta: Meta, body: string}`.
  - `slugify(s) → string`, `uniqueSlug(base, taken: Set<string>) → string`, `scriptPath(context, project, slug) → string`.
  - `parseScriptPath(path) → {context, project, slug} | null` and `draftKey(path) → string` (matches `^[a-z0-9-]{1,120}$`).
  - `async freeScriptPath({context, project, title, exists: (path) => Promise<boolean>}) → string`.
- Produces from `backend.js`. `plugin` is the renderer `PluginApi`.
  - `call(plugin, method, path, body?) → data`, which throws `Error` carrying `.status`.
  - `readScript(plugin, path) → {meta, body} | null` (null on 404) and `writeScript(plugin, path, meta, body)`.
  - `listProjects(plugin) → Project[]`, where `Project = {id, context, slug, name, description, archived}`.
  - `listContexts(plugin) → string[]` and `createProject(plugin, context, name) → Project`.

- [ ] **Step 1: Write the failing tests**

`plugins/script-writer/src/fountain/__tests__/document.test.js`:
```js
import { describe, expect, it } from 'vitest';
import {
  DEFAULT_META, draftKey, freeScriptPath, fromFountain, normalizeMeta, parseScriptPath,
  scriptPath, serializeFile, slugify, toFountain, uniqueSlug,
} from '../document.js';

describe('meta + file', () => {
  it('normalises frontmatter, coercing types and defaulting missing keys', () => {
    const m = normalizeMeta({ title: 'Night', scene_numbers: 'yes', draft_date: 20260930, extra: 1 });
    expect(m).toEqual({ ...DEFAULT_META, title: 'Night', scene_numbers: true, draft_date: '20260930' });
  });

  it('serialises frontmatter as YAML-safe JSON strings with the body after it', () => {
    const out = serializeFile({ title: 'He said "hi": ok', scene_numbers: false }, '\n\nFADE IN:');
    expect(out).toBe([
      '---', 'type: screenplay', 'title: "He said \\"hi\\": ok"', 'credit: "Written by"', 'author: ""',
      'source: ""', 'draft_date: ""', 'contact: ""', 'scene_numbers: false', 'updated: ""', '---', 'FADE IN:',
    ].join('\n'));
  });
});

describe('Fountain title page', () => {
  it('writes a title page from meta, with multi-line values indented', () => {
    const out = toFountain({ title: 'Night', author: 'J R', contact: 'a@b.c\n555 1234' }, 'FADE IN:');
    expect(out).toBe('Title: Night\nCredit: Written by\nAuthor: J R\nContact:\n    a@b.c\n    555 1234\n\nFADE IN:');
  });

  it('round-trips through fromFountain', () => {
    const meta = { ...DEFAULT_META, title: 'Night', author: 'J R', contact: 'a@b.c\n555 1234', draft_date: '2026-09-30' };
    const { meta: back, body } = fromFountain(toFountain(meta, 'INT. A - DAY\n\nGo.'));
    expect(back).toEqual(meta);
    expect(body).toBe('INT. A - DAY\n\nGo.');
  });

  it('does not treat FADE IN: as a title page', () => {
    const r = fromFountain('FADE IN:\n\nINT. A - DAY');
    expect(r.meta).toEqual(DEFAULT_META);
    expect(r.body).toBe('FADE IN:\n\nINT. A - DAY');
  });

  it('handles CRLF and Authors alias', () => {
    const r = fromFountain('Title: X\r\nAuthors: Y\r\n\r\nGo.');
    expect(r.meta).toMatchObject({ title: 'X', author: 'Y' });
    expect(r.body).toBe('Go.');
  });
});

describe('slugs + paths', () => {
  it('slugifies titles', () => {
    expect(slugify('The Long Night!')).toBe('the-long-night');
    expect(slugify('Café  Noir')).toBe('cafe-noir');
    expect(slugify('***')).toBe('untitled');
  });

  it('dedupes slugs', () => {
    expect(uniqueSlug('a', new Set(['a', 'a-2']))).toBe('a-3');
  });

  it('builds and parses script paths', () => {
    const p = scriptPath('personal', 'long-night', 'draft');
    expect(p).toBe('20-contexts/personal/projects/long-night/draft.screenplay.md');
    expect(parseScriptPath(p)).toEqual({ context: 'personal', project: 'long-night', slug: 'draft' });
    expect(parseScriptPath('10-daily/x.md')).toBeNull();
  });

  it('derives filesystem-safe draft keys', () => {
    expect(draftKey('20-contexts/personal/projects/long-night/draft.screenplay.md'))
      .toBe('20-contexts-personal-projects-long-night-draft-screenplay-md');
  });

  it('never picks a path that already exists', async () => {
    const existing = new Set([
      '20-contexts/personal/projects/p/night.screenplay.md',
      '20-contexts/personal/projects/p/night-2.screenplay.md',
    ]);
    const path = await freeScriptPath({ context: 'personal', project: 'p', title: 'Night', exists: async (x) => existing.has(x) });
    expect(path).toBe('20-contexts/personal/projects/p/night-3.screenplay.md');
  });
});
```

`plugins/script-writer/src/api/__tests__/backend.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { createProject, listContexts, readScript, writeScript } from '../backend.js';

function fakePlugin(routes) {
  const calls = [];
  return {
    calls,
    api: {
      fetch: async (method, path, body) => {
        calls.push({ method, path, body });
        const h = routes[`${method} ${path.split('?')[0]}`];
        return h ? h(path, body) : { ok: false, error: 'no route', status: 500 };
      },
    },
  };
}

describe('backend', () => {
  it('reads a script, normalising meta; returns null on 404', async () => {
    const p = fakePlugin({
      'GET /v1/notes': (path) => (path.includes('missing')
        ? { ok: false, error: 'Note not found', status: 404 }
        : { ok: true, data: { body: 'FADE IN:', frontmatter: { title: 'X', scene_numbers: true } } }),
    });
    expect(await readScript(p, 'a/b.screenplay.md')).toMatchObject({ meta: { title: 'X', scene_numbers: true }, body: 'FADE IN:' });
    expect(await readScript(p, 'missing.md')).toBeNull();
    expect(p.calls[0].path).toBe('/v1/notes?path=a%2Fb.screenplay.md');
  });

  it('writes the full file via PUT and surfaces errors', async () => {
    const p = fakePlugin({ 'PUT /v1/notes': () => ({ ok: false, error: 'disk full', status: 500 }) });
    await expect(writeScript(p, 'a.md', { title: 'X' }, 'Go.')).rejects.toThrow('disk full');
    expect(p.calls[0].body.content).toMatch(/^---\ntype: screenplay\n/);
  });

  it('lists contexts', async () => {
    const p = fakePlugin({ 'GET /v1/vault/contexts': () => ({ ok: true, data: { contexts: ['personal', 'codeship'], archived: [] } }) });
    expect(await listContexts(p)).toEqual(['personal', 'codeship']);
  });

  it('createProject falls back to the existing project on 409', async () => {
    const existing = { id: 'personal/long-night', context: 'personal', slug: 'long-night', name: 'Long Night' };
    const p = fakePlugin({
      'POST /v1/projects': () => ({ ok: false, error: 'exists', status: 409 }),
      'GET /v1/projects': () => ({ ok: true, data: [existing] }),
    });
    expect(await createProject(p, 'personal', 'long night')).toEqual(existing);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/fountain/__tests__/document.test.js src/api
```
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement `document.js`**

`plugins/script-writer/src/fountain/document.js`:
```js
// Script file model: frontmatter ⇄ meta, Fountain title page ⇄ meta, slugs, paths.

export const DEFAULT_META = Object.freeze({
  title: 'Untitled', credit: 'Written by', author: '', source: '',
  draft_date: '', contact: '', scene_numbers: false, updated: '',
});
const KEYS = ['title', 'credit', 'author', 'source', 'draft_date', 'contact', 'scene_numbers', 'updated'];
const TITLE_KEYS = [
  ['title', 'Title'], ['credit', 'Credit'], ['author', 'Author'],
  ['source', 'Source'], ['draft_date', 'Draft date'], ['contact', 'Contact'],
];
const LABEL_TO_KEY = { ...Object.fromEntries(TITLE_KEYS.map(([k, l]) => [l.toLowerCase(), k])), authors: 'author' };

export function normalizeMeta(fm = {}) {
  const m = { ...DEFAULT_META };
  for (const k of KEYS) {
    const v = fm?.[k];
    if (v === undefined || v === null) continue;
    m[k] = k === 'scene_numbers' ? Boolean(v) : String(v);
  }
  return m;
}

export function serializeFile(meta, body) {
  const m = normalizeMeta(meta);
  const fm = KEYS.map((k) => `${k}: ${k === 'scene_numbers' ? String(m[k]) : JSON.stringify(m[k])}`);
  return ['---', 'type: screenplay', ...fm, '---', String(body ?? '').replace(/^\n+/, '')].join('\n');
}

export function toFountain(meta, body) {
  const m = normalizeMeta(meta);
  const tp = TITLE_KEYS.filter(([k]) => m[k]).map(([k, label]) => (
    m[k].includes('\n') ? `${label}:\n${m[k].split('\n').map((l) => `    ${l}`).join('\n')}` : `${label}: ${m[k]}`
  ));
  return (tp.length ? `${tp.join('\n')}\n\n` : '') + String(body ?? '').replace(/^\n+/, '');
}

export function fromFountain(text) {
  const src = String(text ?? '').replace(/\r\n?/g, '\n');
  const lines = src.split('\n');
  const first = lines[0]?.match(/^([A-Za-z][A-Za-z ]*):/);
  if (!first || !LABEL_TO_KEY[first[1].toLowerCase()]) return { meta: { ...DEFAULT_META }, body: src };
  const found = {};
  let key = null;
  let i = 0;
  for (; i < lines.length && lines[i].trim() !== ''; i++) {
    const m = lines[i].match(/^([A-Za-z][A-Za-z ]*):\s*(.*)$/);
    if (m && !/^\s/.test(lines[i])) {
      key = LABEL_TO_KEY[m[1].toLowerCase()] ?? null;
      if (key) found[key] = m[2].trim();
    } else if (key) {
      found[key] = found[key] ? `${found[key]}\n${lines[i].trim()}` : lines[i].trim();
    }
  }
  return { meta: normalizeMeta(found), body: lines.slice(i).join('\n').replace(/^\n+/, '') };
}

export function slugify(s) {
  const slug = String(s ?? '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60).replace(/-+$/, '');
  return slug || 'untitled';
}

export function uniqueSlug(base, taken) {
  let s = base;
  for (let n = 2; taken.has(s); n++) s = `${base}-${n}`;
  return s;
}

export const scriptPath = (context, project, slug) => `20-contexts/${context}/projects/${project}/${slug}.screenplay.md`;

export function parseScriptPath(path) {
  const m = String(path).match(/^20-contexts\/([^/]+)\/projects\/([^/]+)\/([^/]+)\.screenplay\.md$/);
  return m ? { context: m[1], project: m[2], slug: m[3] } : null;
}

export function draftKey(path) {
  return String(path).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(-120) || 'draft';
}

export async function freeScriptPath({ context, project, title, exists }) {
  const base = slugify(title);
  const taken = new Set();
  for (let guard = 0; guard < 100; guard++) {
    const slug = uniqueSlug(base, taken);
    const path = scriptPath(context, project, slug);
    if (!(await exists(path))) return path;
    taken.add(slug);
  }
  throw new Error(`could not find a free file name for "${title}"`);
}
```

- [ ] **Step 4: Implement `backend.js`**

`plugins/script-writer/src/api/backend.js`:
```js
// Thin client over plugin.api.fetch (resolves {ok,data}|{ok:false,error,status}).
import { normalizeMeta, serializeFile, slugify } from '../fountain/document.js';

export async function call(plugin, method, path, body) {
  const r = await plugin.api.fetch(method, path, body);
  if (!r || !r.ok) {
    const err = new Error(r?.error ?? `${method} ${path} failed`);
    err.status = r?.status;
    throw err;
  }
  return r.data;
}

export async function readScript(plugin, path) {
  try {
    const d = await call(plugin, 'GET', `/v1/notes?path=${encodeURIComponent(path)}`);
    return { meta: normalizeMeta(d.frontmatter), body: d.body ?? '' };
  } catch (e) {
    if (e.status === 404) return null;
    throw e;
  }
}

export async function writeScript(plugin, path, meta, body) {
  await call(plugin, 'PUT', '/v1/notes', { path, content: serializeFile(meta, body) });
}

export const listProjects = (plugin) => call(plugin, 'GET', '/v1/projects');

export async function listContexts(plugin) {
  const d = await call(plugin, 'GET', '/v1/vault/contexts');
  return Array.isArray(d?.contexts) ? d.contexts : [];
}

export async function createProject(plugin, context, name) {
  try {
    return await call(plugin, 'POST', '/v1/projects', { context, name });
  } catch (e) {
    if (e.status !== 409) throw e;
    const all = await listProjects(plugin);
    const hit = all.find((p) => p.context === context
      && (p.name.toLowerCase() === name.toLowerCase() || p.slug === slugify(name)));
    if (!hit) throw e;
    return hit;
  }
}
```

- [ ] **Step 5: Run tests**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/fountain src/api
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer/src && git commit -m "feat(script-writer): document model + backend client

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Word-wrap and paginator

**Files:**
- Create: `plugins/script-writer/src/paginate/wrap.js`, `plugins/script-writer/src/paginate/paginate.js`
- Test: `plugins/script-writer/src/paginate/__tests__/wrap.test.js`, `plugins/script-writer/src/paginate/__tests__/paginate.test.js`

**Interfaces:**
- Consumes: `parse` (Task 2).
- Produces:
  - `visibleLength(s) → number` (emphasis markers don't count) and `wrap(text, width) → string[]` (honours `\n` hard breaks).
  - `LINES_PER_PAGE = 54`, `LAYOUT`.
  - `paginate(elements, {sceneNumbers?: boolean, linesPerPage?: number}) → Page[]`, where `Page = {number, lines: Line[]}`.
  - `Line = {type, text, x, y, el, sceneNumber?, italic?}`:
    - `type` is an element type, or `more` for `(MORE)`.
    - `x` is the column from the text left, and `y` is the row from the top of the body (0–53).
    - `el` is the element index, or `-1` for synthesized lines.

- [ ] **Step 1: Write the failing wrap tests**

`plugins/script-writer/src/paginate/__tests__/wrap.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { visibleLength, wrap } from '../wrap.js';

describe('wrap', () => {
  it('wraps greedily at the width', () => {
    expect(wrap('aaa bbb ccc', 7)).toEqual(['aaa bbb', 'ccc']);
  });
  it('honours hard line breaks and keeps empty lines', () => {
    expect(wrap('one\n\ntwo', 10)).toEqual(['one', '', 'two']);
  });
  it('hard-splits words longer than the width', () => {
    expect(wrap('abcdefghij', 4)).toEqual(['abcd', 'efgh', 'ij']);
  });
  it('does not count emphasis markers toward width', () => {
    expect(visibleLength('**bold** _u_ \\*')).toBe(8);
    expect(wrap('**aaa** bbb', 7)).toEqual(['**aaa** bbb']);
  });
});
```

- [ ] **Step 2: Implement `wrap.js`**

`plugins/script-writer/src/paginate/wrap.js`:
```js
/** Printed length: emphasis markers (* _) don't print; an escaped \* prints one char. */
export function visibleLength(s) {
  return s.replace(/\\[*_]/g, 'x').replace(/[*_]/g, '').length;
}

export function wrap(text, width) {
  const out = [];
  for (const para of String(text).split('\n')) {
    const words = para.trim() === '' ? [] : para.trim().split(/ +/);
    let line = '';
    for (let w of words) {
      while (visibleLength(w) > width) {
        if (line) { out.push(line); line = ''; }
        out.push(w.slice(0, width));
        w = w.slice(width);
      }
      const candidate = line ? `${line} ${w}` : w;
      if (visibleLength(candidate) <= width) line = candidate;
      else { out.push(line); line = w; }
    }
    out.push(line);
  }
  return out;
}
```

- [ ] **Step 3: Run the wrap tests**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/paginate/__tests__/wrap.test.js
```
Expected: PASS.

- [ ] **Step 4: Write the failing paginate tests**

`plugins/script-writer/src/paginate/__tests__/paginate.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { parse } from '../../fountain/parse.js';
import { LINES_PER_PAGE, paginate } from '../paginate.js';

const P = (src, opts) => paginate(parse(src), opts);
// n one-line actions occupy rows 0..2n-2 (blank line between blocks).
const actions = (n) => Array.from({ length: n }, (_, k) => `Action ${k + 1}.`).join('\n\n');
const sentences = (n, end = '.') => Array.from({ length: n }, (_, k) => `Line ${k + 1} of it${end}`).join('\n');

describe('paginate', () => {
  it('returns one empty page for an empty script', () => {
    expect(P('')).toEqual([{ number: 1, lines: [] }]);
  });

  it('positions elements with one blank line between blocks', () => {
    const [page] = P('INT. HOUSE - DAY\n\nShe waits.\n\nMARA\n(beat)\nNow.');
    expect(page.lines.map((l) => [l.type, l.y, l.x])).toEqual([
      ['scene_heading', 0, 0], ['action', 2, 0], ['character', 4, 22], ['parenthetical', 5, 16], ['dialogue', 6, 10],
    ]);
  });

  it('uppercases headings/cues/transitions and right-aligns transitions', () => {
    const [page] = P('ext. beach - day\n\nGo.\n\ncut to:\n\n');
    expect(page.lines[0].text).toBe('EXT. BEACH - DAY');
    const tr = P('Go.\n\n> fade out.')[0].lines[1];
    expect(tr).toMatchObject({ type: 'transition', text: 'FADE OUT.', x: 60 - 'FADE OUT.'.length });
  });

  it('fits exactly 27 one-line actions on a 54-line page', () => {
    const pages = P(actions(28));
    expect(pages).toHaveLength(2);
    expect(pages[0].lines).toHaveLength(27);
    expect(pages[0].lines.at(-1).y).toBe(52);
    expect(pages[1].lines[0]).toMatchObject({ y: 0, text: 'Action 28.' });
  });

  it('never leaves a scene heading at the bottom of a page', () => {
    const pages = P(`${actions(26)}\n\nINT. CAVE - NIGHT\n\nDark.`);
    expect(pages[0].lines.at(-1).type).toBe('action');
    expect(pages[1].lines[0]).toMatchObject({ type: 'scene_heading', y: 0 });
  });

  it('splits long dialogue with (MORE) and CONT\'D, ≥2 lines each side', () => {
    const pages = P(`${actions(20)}\n\nMARA\n${sentences(20)}`);
    const p1 = pages[0].lines;
    expect(p1.at(-1)).toMatchObject({ type: 'more', text: '(MORE)', y: 53, x: 22 });
    expect(p1.filter((l) => l.type === 'dialogue')).toHaveLength(12);
    expect(pages[1].lines[0]).toMatchObject({ type: 'character', text: "MARA (CONT'D)", y: 0 });
    expect(pages[1].lines.filter((l) => l.type === 'dialogue')).toHaveLength(8);
  });

  it('prefers a sentence boundary when splitting dialogue', () => {
    const lines = Array.from({ length: 20 }, (_, k) => (k === 9 ? 'Stop here.' : 'and on'));
    const pages = P(`${actions(20)}\n\nMARA\n${lines.join('\n')}`);
    expect(pages[0].lines.filter((l) => l.type === 'dialogue').at(-1).text).toBe('Stop here.');
  });

  it('moves a short dialogue block whole instead of splitting it', () => {
    const pages = P(`${actions(26)}\n\nMARA\nOne.\nTwo.\nThree.`);
    expect(pages[0].lines.some((l) => l.type === 'character')).toBe(false);
    expect(pages[1].lines[0]).toMatchObject({ type: 'character', text: 'MARA' });
  });

  it('splits action at a sentence end, otherwise moves it whole', () => {
    const split = P(`${actions(20)}\n\n${sentences(20)}`);
    expect(split[0].lines.at(-1)).toMatchObject({ y: 53, text: 'Line 14 of it.' });
    expect(split[1].lines[0]).toMatchObject({ y: 0, text: 'Line 15 of it.' });

    const moved = P(`${actions(20)}\n\n${sentences(20, '')}`);
    expect(moved[0].lines.at(-1).text).toBe('Action 20.');
    expect(moved[1].lines[0].text).toBe('Line 1 of it');
  });

  it('honours forced page breaks', () => {
    const pages = P('One.\n\n===\n\nTwo.');
    expect(pages.map((p) => p.lines.map((l) => l.text))).toEqual([['One.'], ['Two.']]);
  });

  it('numbers scenes when asked, keeping explicit numbers', () => {
    const [page] = P('INT. A - DAY\n\nx\n\nINT. B - DAY #7B#\n\ny\n\nINT. C - DAY', { sceneNumbers: true });
    expect(page.lines.filter((l) => l.sceneNumber).map((l) => l.sceneNumber)).toEqual(['1', '7B', '3']);
    expect(P('INT. A - DAY')[0].lines[0].sceneNumber).toBeUndefined();
  });

  it('lays dual dialogue side by side', () => {
    const [page] = P('BRICK\nScrew it.\n\nSTEEL ^\nScrew it.');
    const cues = page.lines.filter((l) => l.type === 'character');
    expect(cues.map((c) => c.y)).toEqual([0, 0]);
    expect(cues[1].x).toBeGreaterThan(cues[0].x + 20);
  });

  it('strips notes and boneyard from printed text', () => {
    const [page] = P('She waits [[fix]] here.');
    expect(page.lines[0].text).toBe('She waits here.');
  });

  it('never loses, duplicates or overflows lines on oversized blocks', () => {
    const src = `INT. A - DAY\n\n${sentences(150, '')}\n\nMARA\n${sentences(120)}\n\n${actions(40)}`;
    const pages = P(src);
    for (const p of pages) {
      for (const l of p.lines) expect(l.y).toBeLessThan(LINES_PER_PAGE);
      expect(p.lines.at(-1)?.type).not.toBe('scene_heading');
    }
    const texts = pages.flatMap((p) => p.lines).filter((l) => l.type !== 'more' && l.el !== -1).map((l) => l.text);
    expect(texts.filter((t) => /^Line \d+ of it$/.test(t))).toHaveLength(150);
    expect(texts.filter((t) => /^Line \d+ of it\.$/.test(t))).toHaveLength(120);
    expect(texts.filter((t) => /^Action \d+\.$/.test(t))).toHaveLength(40);
  });
});
```

- [ ] **Step 5: Run to verify they fail**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/paginate/__tests__/paginate.test.js
```
Expected: FAIL (module not found).

- [ ] **Step 6: Implement `paginate.js`**

`plugins/script-writer/src/paginate/paginate.js`:
```js
// Elements → positioned page lines using standard screenplay geometry
// (Courier 12pt: 10 cpi, 6 lpi; 1.5"/1" margins → 60 cols × 54 rows).
import { visibleLength, wrap } from './wrap.js';

export const LINES_PER_PAGE = 54;
export const LAYOUT = {
  scene_heading: { x: 0, width: 60, upper: true },
  action: { x: 0, width: 60 },
  character: { x: 22, width: 38, upper: true },
  parenthetical: { x: 16, width: 25 },
  dialogue: { x: 10, width: 35 },
  transition: { x: 0, width: 60, upper: true, align: 'right' },
  centered: { x: 0, width: 60, align: 'center' },
  lyric: { x: 0, width: 60, italic: true },
};
const DUAL = {
  character: { x: 8, width: 20, upper: true },
  parenthetical: { x: 4, width: 22 },
  dialogue: { x: 0, width: 28 },
};
const DUAL_RIGHT = 31;
const SENTENCE_END = /[.!?…]["'”’)]*$/;

const clean = (s) => s.replace(/\[\[[\s\S]*?\]\]/g, '').replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/ {2,}/g, ' ').replace(/[ \t]+$/gm, '');

function layout(type, text, spec, el, base = 0) {
  const t = spec.upper ? clean(text).toUpperCase() : clean(text);
  return wrap(t, spec.width).map((w) => {
    let x = base + spec.x;
    if (spec.align === 'right') x = base + spec.width - visibleLength(w);
    if (spec.align === 'center') x = base + Math.floor((spec.width - visibleLength(w)) / 2);
    return spec.italic ? { type, text: w, x, el, italic: true } : { type, text: w, x, el };
  });
}

function toBlocks(elements, sceneNumbers) {
  const blocks = [];
  let scene = 0;
  for (let k = 0; k < elements.length; k++) {
    const el = elements[k];
    if (el.type === 'page_break') { blocks.push({ kind: 'break' }); continue; }
    if (el.type === 'character') {
      const parts = [{ el, idx: k }];
      while (k + 1 < elements.length && (elements[k + 1].type === 'dialogue' || elements[k + 1].type === 'parenthetical')) {
        k++;
        parts.push({ el: elements[k], idx: k });
      }
      const lay = (L, base) => parts.flatMap((p) => layout(p.el.type, p.el.text, L[p.el.type], p.idx, base));
      const block = { kind: 'dialogue', dual: el.dual, cue: clean(el.text).toUpperCase(), lines: lay(LAYOUT, 0), narrow: (b) => lay(DUAL, b) };
      const prev = blocks[blocks.length - 1];
      if (el.dual === 'right' && prev?.kind === 'dialogue' && prev.dual === 'left') {
        blocks[blocks.length - 1] = { kind: 'dual', left: prev.narrow(0), right: block.narrow(DUAL_RIGHT) };
      } else {
        blocks.push(block);
      }
      continue;
    }
    const spec = LAYOUT[el.type];
    if (!spec) continue; // sections, synopses, notes, boneyard don't print
    const lines = layout(el.type, el.text, spec, k);
    if (el.type === 'scene_heading') {
      scene++;
      const num = el.sceneNumber ?? (sceneNumbers ? String(scene) : undefined);
      if (num && lines[0]) lines[0].sceneNumber = num;
    }
    blocks.push({ kind: el.type, lines });
  }
  return blocks;
}

const height = (b) => (b.kind === 'dual' ? Math.max(b.left.length, b.right.length) : b.lines.length);

export function paginate(elements, { sceneNumbers = false, linesPerPage = LINES_PER_PAGE } = {}) {
  const blocks = toBlocks(elements, sceneNumbers);
  const pages = [];
  let page;
  let y;
  const newPage = () => { page = { number: pages.length + 1, lines: [] }; pages.push(page); y = 0; };
  const top = () => (y === 0 ? 0 : y + 1);
  const fits = (n) => top() + n <= linesPerPage;
  const put = (lines, at) => {
    lines.forEach((l, n) => page.lines.push({ ...l, y: at + n }));
    y = at + lines.length;
  };
  const putForced = (lines) => {
    let rest = lines;
    while (rest.length) {
      let at = top();
      if (at >= linesPerPage) { newPage(); at = 0; }
      const room = linesPerPage - at;
      put(rest.slice(0, room), at);
      rest = rest.slice(room);
      if (rest.length) newPage();
    }
  };
  // Move a block that can't split to the next page — unless the page ends in
  // the scene heading that owns it; then force-split rather than orphan it.
  const moveWhole = (lines) => {
    const afterHeading = page.lines.length > 0 && page.lines[page.lines.length - 1].type === 'scene_heading';
    if (y > 0 && !afterHeading) newPage();
    putForced(lines);
  };
  const splitAction = (lines) => {
    const at = top();
    for (let k = Math.min(linesPerPage - at, lines.length - 2); k >= 2; k--) {
      if (!SENTENCE_END.test(lines[k - 1].text)) continue;
      put(lines.slice(0, k), at);
      newPage();
      putForced(lines.slice(k));
      return true;
    }
    return false;
  };
  const splitDialogue = ({ lines, cue }) => {
    const at = top();
    const valid = (k) => lines.length - k >= 2
      && lines[k - 1].type !== 'parenthetical' && lines[k - 1].type !== 'character' && lines[k].type !== 'character';
    let best = -1;
    for (let k = Math.min(linesPerPage - at - 1, lines.length - 2); k >= 3; k--) {
      if (!valid(k)) continue;
      if (best < 0) best = k;
      if (lines[k - 1].type === 'dialogue' && SENTENCE_END.test(lines[k - 1].text)) { best = k; break; }
    }
    if (best < 0) return false;
    put([...lines.slice(0, best), { type: 'more', text: '(MORE)', x: LAYOUT.character.x, el: -1 }], at);
    newPage();
    const contd = /\(CONT['’]D\)/i.test(cue) ? cue : `${cue} (CONT'D)`;
    putForced([{ type: 'character', text: contd, x: LAYOUT.character.x, el: -1 }, ...lines.slice(best)]);
    return true;
  };

  newPage();
  for (let b = 0; b < blocks.length; b++) {
    const block = blocks[b];
    if (block.kind === 'break') { if (y > 0) newPage(); continue; }
    if (block.kind === 'dual') {
      const h = height(block);
      if (!fits(h) && y > 0) newPage();
      const at = top();
      block.left.forEach((l, n) => page.lines.push({ ...l, y: at + n }));
      block.right.forEach((l, n) => page.lines.push({ ...l, y: at + n }));
      y = at + h;
      continue;
    }
    const { lines } = block;
    if (block.kind === 'scene_heading') {
      const next = blocks[b + 1];
      const keep = next && next.kind !== 'break' ? 1 + Math.min(2, height(next)) : 0;
      if (!fits(lines.length + keep) && y > 0) newPage();
      put(lines, top());
      continue;
    }
    if (fits(lines.length)) { put(lines, top()); continue; }
    if (block.kind === 'action' && splitAction(lines)) continue;
    if (block.kind === 'dialogue' && splitDialogue(block)) continue;
    moveWhole(lines);
  }
  if (pages.length > 1 && pages[pages.length - 1].lines.length === 0) pages.pop();
  return pages;
}
```

- [ ] **Step 7: Run tests**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/paginate
```
Expected: PASS. If the dialogue-split test's line counts differ, re-derive them by hand before changing code:
- 20 actions occupy rows 0–38, so the cue starts at row 40.
- The rows left, minus one for `(MORE)`, leave room for 13 lines: the cue plus 12 dialogue lines. Every line ends with `.`, so the split is k = 13.

- [ ] **Step 8: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer/src/paginate && git commit -m "feat(script-writer): word-wrap + industry-standard paginator

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Page HTML renderer

**Files:**
- Create: `plugins/script-writer/src/render/pageHtml.js`
- Test: `plugins/script-writer/src/render/__tests__/pageHtml.test.js`

**Interfaces:**
- Consumes: `Page`/`Line` (Task 4) and `normalizeMeta` (Task 3).
- Produces:
  - `FONT_PLACEHOLDER = '__FONT_BASE__'` and `FONT_FILES: string[]`.
  - `inlineHtml(text, state) → string`. `state` is `{b,i,u}` and is mutated.
  - `renderPage(page) → string`, `renderTitlePage(meta) → string` (`''` when the title is empty), and `pageCss(paper: 'letter'|'a4') → string`.
  - `fontFaceCss(base: string) → string` and `documentHtml({meta, pages, paper, fontBase}) → string`, which starts with `<!doctype html>`.

- [ ] **Step 1: Write the failing tests**

`plugins/script-writer/src/render/__tests__/pageHtml.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { parse } from '../../fountain/parse.js';
import { paginate } from '../../paginate/paginate.js';
import { documentHtml, FONT_FILES, fontFaceCss, inlineHtml, renderPage, renderTitlePage } from '../pageHtml.js';

const fresh = () => ({ b: false, i: false, u: false });

describe('inlineHtml', () => {
  it('escapes HTML and renders emphasis as classed spans', () => {
    expect(inlineHtml('a <b> & **bold** *it* _u_ \\*x', fresh()))
      .toBe('a &lt;b&gt; &amp; <span class="b">bold</span> <span class="i">it</span> <span class="u">u</span> *x');
  });
  it('carries emphasis state across lines of one element', () => {
    const s = fresh();
    expect(inlineHtml('*start', s)).toBe('<span class="i">start</span>');
    expect(inlineHtml('end* now', s)).toBe('<span class="i">end</span> now');
  });
});

describe('renderPage', () => {
  it('positions lines in inches from the page edge and numbers pages from 2', () => {
    const pages = paginate(parse('INT. A - DAY #4#\n\nGo.\n\n===\n\nMore.'));
    const p1 = renderPage(pages[0]);
    expect(p1).toContain('class="sw-ln sw-t-scene_heading" style="top:1.0000in;left:1.50in"');
    expect(p1).toContain('class="sw-ln sw-sn" style="top:1.0000in;left:0.75in">4</div>');
    expect(p1).not.toContain('sw-pn');
    expect(renderPage(pages[1])).toContain('<div class="sw-ln sw-pn" style="top:0.5in;right:1in">2.</div>');
  });
});

describe('title page + document', () => {
  it('renders nothing without a title and escapes values', () => {
    expect(renderTitlePage({ title: '' })).toBe('');
    expect(renderTitlePage({ title: 'A <B>', author: 'Me' })).toContain('A &lt;B&gt;');
  });
  it('builds a full printable document with font faces', () => {
    const html = documentHtml({ meta: { title: 'X' }, pages: paginate(parse('Go.')), paper: 'a4', fontBase: '__FONT_BASE__' });
    expect(html.startsWith('<!doctype html>')).toBe(true);
    expect(html).toContain('@page{size:A4;margin:0}');
    for (const f of FONT_FILES) expect(html).toContain(`__FONT_BASE__${f}`);
    expect(fontFaceCss('B/')).toContain("font-family:'Courier Prime'");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/render
```
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `pageHtml.js`**

`plugins/script-writer/src/render/pageHtml.js`:
```js
// Page[] → absolutely positioned HTML. One renderer for the in-app page view
// and the PDF, so what you see is what prints.
import { normalizeMeta } from '../fountain/document.js';

export const FONT_PLACEHOLDER = '__FONT_BASE__';
export const FONT_FILES = [
  'courier-prime-latin-400-normal.woff2', 'courier-prime-latin-400-italic.woff2',
  'courier-prime-latin-700-normal.woff2', 'courier-prime-latin-700-italic.woff2',
];

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };
const esc = (s) => s.replace(/[&<>"]/g, (c) => ESC[c]);
const top = (y) => `${(1 + y / 6).toFixed(4)}in`;
const left = (x) => `${(1.5 + x / 10).toFixed(2)}in`;
const fresh = () => ({ b: false, i: false, u: false });

export function inlineHtml(text, state) {
  let html = '';
  let last = 0;
  const flush = (s) => {
    if (!s) return;
    const cls = ['b', 'i', 'u'].filter((k) => state[k]).join(' ');
    html += cls ? `<span class="${cls}">${esc(s)}</span>` : esc(s);
  };
  for (const m of text.matchAll(/\\([*_])|\*\*\*|\*\*|\*|_/g)) {
    flush(text.slice(last, m.index));
    last = m.index + m[0].length;
    if (m[1]) { flush(m[1]); continue; }
    if (m[0] === '***') { state.b = !state.b; state.i = !state.i; } else if (m[0] === '**') state.b = !state.b;
    else if (m[0] === '*') state.i = !state.i;
    else state.u = !state.u;
  }
  flush(text.slice(last));
  return html;
}

export function renderPage(page) {
  let html = '<div class="sw-page">';
  if (page.number > 1) html += `<div class="sw-ln sw-pn" style="top:0.5in;right:1in">${page.number}.</div>`;
  let state = fresh();
  let lastEl = null;
  for (const l of page.lines) {
    if (l.el !== lastEl || l.el === -1) { state = fresh(); lastEl = l.el; }
    const cls = `sw-ln sw-t-${l.type}${l.italic ? ' sw-italic' : ''}`;
    html += `<div class="${cls}" style="top:${top(l.y)};left:${left(l.x)}">${inlineHtml(l.text, state)}</div>`;
    if (l.sceneNumber) {
      const n = esc(l.sceneNumber);
      html += `<div class="sw-ln sw-sn" style="top:${top(l.y)};left:0.75in">${n}</div>`;
      html += `<div class="sw-ln sw-sn" style="top:${top(l.y)};left:7.6in">${n}</div>`;
    }
  }
  return `${html}</div>`;
}

export function renderTitlePage(meta) {
  const m = normalizeMeta(meta);
  if (!m.title.trim()) return '';
  let html = '<div class="sw-page sw-title-page">';
  const block = (y0, value, cls, pos) => value.split('\n').forEach((line, n) => {
    const style = pos === 'center' ? `top:${top(y0 + n)}` : `top:${top(y0 + n)};left:1.5in`;
    html += `<div class="sw-ln ${cls}" style="${style}">${inlineHtml(line, fresh())}</div>`;
  });
  block(18, m.title.toUpperCase(), 'sw-center sw-tp-title', 'center');
  if (m.credit) block(21, m.credit, 'sw-center', 'center');
  if (m.author) block(23, m.author, 'sw-center', 'center');
  if (m.source) block(26, m.source, 'sw-center', 'center');
  if (m.draft_date) block(46, m.draft_date, '', 'left');
  if (m.contact) block(48, m.contact, '', 'left');
  return `${html}</div>`;
}

export function pageCss(paper = 'letter') {
  const [w, h] = paper === 'a4' ? ['8.27in', '11.69in'] : ['8.5in', '11in'];
  return [
    `.sw-page{position:relative;width:${w};height:${h};background:#fff;color:#111;box-sizing:border-box;overflow:hidden;`,
    "font-family:'Courier Prime','Courier New',Courier,monospace;font-size:12pt}",
    `.sw-ln{position:absolute;white-space:pre;line-height:${(1 / 6).toFixed(4)}in}`,
    '.sw-t-scene_heading{font-weight:700}.sw-italic{font-style:italic}',
    '.sw-center{left:1.5in;width:6in;text-align:center}.sw-tp-title{font-weight:700;text-decoration:underline}',
    '.sw-page .b{font-weight:700}.sw-page .i{font-style:italic}.sw-page .u{text-decoration:underline}',
  ].join('');
}

export function fontFaceCss(base) {
  return FONT_FILES.map((f) => {
    const [, weight, style] = f.match(/-(\d{3})-(normal|italic)\.woff2$/);
    return `@font-face{font-family:'Courier Prime';font-weight:${weight};font-style:${style};src:url("${base}${f}") format("woff2")}`;
  }).join('');
}

export function documentHtml({ meta, pages, paper = 'letter', fontBase = FONT_PLACEHOLDER }) {
  const size = paper === 'a4' ? 'A4' : 'letter';
  const css = `${fontFaceCss(fontBase)}@page{size:${size};margin:0}html,body{margin:0;padding:0}${pageCss(paper)}`
    + '.sw-page{break-after:page}.sw-page:last-child{break-after:auto}';
  return `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body>${renderTitlePage(meta)}${pages.map(renderPage).join('')}</body></html>`;
}
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/render
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer/src/render && git commit -m "feat(script-writer): page/title-page HTML renderer + printable document

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Outline (scenes, characters, scene reorder)

**Files:**
- Create: `plugins/script-writer/src/fountain/outline.js`
- Test: `plugins/script-writer/src/fountain/__tests__/outline.test.js`

**Interfaces:**
- Consumes: `parse` (Task 2).
- Produces:
  - `scenes(elements) → {index, number, heading, line, synopsis}[]`
  - `cueName(text) → string`
  - `characters(elements) → {name, count, lines: number[]}[]`, sorted by count desc then name.
  - `moveScene(text, from, to) → string`

- [ ] **Step 1: Write the failing tests**

`plugins/script-writer/src/fountain/__tests__/outline.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { parse } from '../parse.js';
import { characters, cueName, moveScene, scenes } from '../outline.js';

const SRC = 'FADE IN:\n\nINT. A - DAY\n\n= Mara arrives.\n\nMARA\nHi.\n\nINT. B - NIGHT #9#\n\nJOE (V.O.)\nYo.\n\nMARA (CONT\'D)\nAgain.\n\nEXT. C - DAY\n\nEnd.\n';

describe('outline', () => {
  it('lists scenes with numbers and first synopsis', () => {
    expect(scenes(parse(SRC))).toEqual([
      { index: 0, number: '1', heading: 'INT. A - DAY', line: 2, synopsis: 'Mara arrives.' },
      { index: 1, number: '9', heading: 'INT. B - NIGHT', line: 9, synopsis: '' },
      { index: 2, number: '3', heading: 'EXT. C - DAY', line: 17, synopsis: '' },
    ]);
  });

  it('normalises cue names', () => {
    expect(cueName("mara (cont'd) ^")).toBe('MARA');
  });

  it('counts speeches per character, most first', () => {
    expect(characters(parse(SRC))).toEqual([
      { name: 'MARA', count: 2, lines: [6, 14] },
      { name: 'JOE', count: 1, lines: [11] },
    ]);
  });

  it('moves a scene block, keeping the preamble and one blank line between scenes', () => {
    const out = moveScene(SRC, 2, 0);
    expect(scenes(parse(out)).map((s) => s.heading)).toEqual(['EXT. C - DAY', 'INT. A - DAY', 'INT. B - NIGHT']);
    expect(out.startsWith('FADE IN:\n\nEXT. C - DAY\n\nEnd.\n\nINT. A - DAY')).toBe(true);
    expect(out.endsWith('Again.\n')).toBe(true);
  });

  it('is a no-op for out-of-range or same-index moves', () => {
    expect(moveScene(SRC, 1, 1)).toBe(SRC);
    expect(moveScene(SRC, 5, 0)).toBe(SRC);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/fountain/__tests__/outline.test.js
```
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `outline.js`**

`plugins/script-writer/src/fountain/outline.js`:
```js
import { parse } from './parse.js';

export function scenes(elements) {
  const out = [];
  for (const el of elements) {
    if (el.type === 'scene_heading') {
      out.push({ heading: el.text.toUpperCase(), line: el.line, sceneNumber: el.sceneNumber, synopsis: '' });
    } else if (el.type === 'synopsis' && out.length && !out[out.length - 1].synopsis) {
      out[out.length - 1].synopsis = el.text;
    }
  }
  return out.map(({ sceneNumber, ...s }, index) => ({ index, number: sceneNumber ?? String(index + 1), ...s }));
}

export const cueName = (text) => text.replace(/^@/, '').replace(/\s*\^\s*$/, '').replace(/\([^)]*\)/g, '').trim().toUpperCase();

export function characters(elements) {
  const map = new Map();
  for (const el of elements) {
    if (el.type !== 'character') continue;
    const name = cueName(el.text);
    if (!name) continue;
    const entry = map.get(name) ?? { name, count: 0, lines: [] };
    entry.count++;
    entry.lines.push(el.line);
    map.set(name, entry);
  }
  return [...map.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

const trimBlankTail = (arr) => {
  const a = [...arr];
  while (a.length && a[a.length - 1].trim() === '') a.pop();
  return a;
};

export function moveScene(text, from, to) {
  const heads = parse(text).filter((e) => e.type === 'scene_heading').map((e) => e.line);
  if (from === to || from < 0 || to < 0 || from >= heads.length || to >= heads.length) return text;
  const lines = text.split('\n');
  const pre = trimBlankTail(lines.slice(0, heads[0]));
  const blocks = heads.map((h, k) => trimBlankTail(lines.slice(h, heads[k + 1] ?? lines.length)));
  const [moved] = blocks.splice(from, 1);
  blocks.splice(to, 0, moved);
  const body = blocks.map((b) => b.join('\n')).join('\n\n');
  return (pre.length ? `${pre.join('\n')}\n\n` : '') + body + (text.endsWith('\n') ? '\n' : '');
}
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/fountain
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer/src/fountain && git commit -m "feat(script-writer): scene/character outline + scene reorder

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Editor element flow (Tab/Enter logic on CodeMirror state)

**Files:**
- Create: `plugins/script-writer/src/editor/analysis.js`, `hints.js`, `flow.js`, `commands.js`
- Test: `plugins/script-writer/src/editor/__tests__/flow.test.js`, `plugins/script-writer/src/editor/__tests__/commands.test.js`

**Interfaces:**
- Consumes: `parse`, `SCENE_PREFIX`, `isUpperCue` (Task 2).
- Produces:
  - `analysisField: StateField<{elements, lineTypes: (string|undefined)[]}>`, where `lineTypes` is indexed 0-based, and `analyze(text)`.
  - `setHint: StateEffectType<{pos, type}>`, `hintField`, and `hintAt(state, lineNo1) → type|null`.
  - From `flow.js`: `CYCLE`, `CAPS_TYPES: Set`, `NEXT_ON_ENTER`, `stripMarkers(text)`, `applyType(text, type)`, `looksLikeCue(text)`, `nextInCycle(current, dir, allowParen)`, and `markerRanges(text, type) → [from, to, cls][]`.
  - From `commands.js`: `typeAt(state, lineNo1) → type|null`, `cycleType(dir) → Command`, `setType(type) → Command`, and `enter: Command`.

- [ ] **Step 1: Write the failing pure-flow tests**

`plugins/script-writer/src/editor/__tests__/flow.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { applyType, looksLikeCue, markerRanges, nextInCycle, stripMarkers } from '../flow.js';

describe('flow', () => {
  it('strips forcing markers and parens', () => {
    expect(stripMarkers('@McCLANE')).toBe('McCLANE');
    expect(stripMarkers('>THE END<')).toBe('THE END');
    expect(stripMarkers('(quietly)')).toBe('quietly');
    expect(stripMarkers('.FLASHBACK')).toBe('FLASHBACK');
  });

  it('rewrites a line for each element type', () => {
    expect(applyType('mara', 'character')).toBe('MARA');
    expect(applyType('quietly', 'parenthetical')).toBe('(quietly)');
    expect(applyType('cut to:', 'transition')).toBe('CUT TO:');
    expect(applyType('fade out.', 'transition')).toBe('>FADE OUT.');
    expect(applyType('int. house - day', 'scene_heading')).toBe('INT. HOUSE - DAY');
    expect(applyType('flashback', 'scene_heading')).toBe('.FLASHBACK');
    expect(applyType('MARA', 'action')).toBe('!MARA');
    expect(applyType('(beat)', 'action')).toBe('beat');
    expect(applyType('the end', 'centered')).toBe('>the end<');
  });

  it('cycles types, only offering parenthetical inside dialogue', () => {
    expect(nextInCycle('action', 1, false)).toBe('character');
    expect(nextInCycle('character', 1, false)).toBe('transition');
    expect(nextInCycle('character', 1, true)).toBe('parenthetical');
    expect(nextInCycle('scene_heading', 1, false)).toBe('action');
    expect(nextInCycle('action', -1, false)).toBe('scene_heading');
    expect(nextInCycle('dialogue', 1, true)).toBe('parenthetical');
    expect(nextInCycle(null, 1, false)).toBe('character');
  });

  it('detects cue-looking lines', () => {
    expect(looksLikeCue('MARA')).toBe(true);
    expect(looksLikeCue('INT. HOUSE')).toBe(false);
    expect(looksLikeCue('CUT TO:')).toBe(false);
    expect(looksLikeCue('Mara')).toBe(false);
  });

  it('finds marker ranges to dim', () => {
    expect(markerRanges('.FLASHBACK', 'scene_heading')).toEqual([[0, 1, 'sw-marker']]);
    expect(markerRanges('INT. A #4#', 'scene_heading')).toEqual([[7, 10, 'sw-marker']]);
    expect(markerRanges('>END<', 'centered')).toEqual([[0, 1, 'sw-marker'], [4, 5, 'sw-marker']]);
    expect(markerRanges('STEEL ^', 'character')).toEqual([[6, 7, 'sw-marker']]);
    expect(markerRanges('Go [[fix]] now', 'action')).toEqual([[3, 10, 'sw-note']]);
  });
});
```

- [ ] **Step 2: Implement `flow.js`**

`plugins/script-writer/src/editor/flow.js`:
```js
// Pure element-flow rules (Final Draft conventions over Fountain text).
import { isUpperCue, SCENE_PREFIX } from '../fountain/parse.js';

export const CYCLE = ['action', 'character', 'parenthetical', 'transition', 'scene_heading'];
export const CAPS_TYPES = new Set(['character', 'scene_heading', 'transition']);
export const NEXT_ON_ENTER = {
  scene_heading: { insert: '\n\n', next: 'action' },
  action: { insert: '\n\n', next: 'action' },
  character: { insert: '\n', next: 'dialogue' },
  parenthetical: { insert: '\n', next: 'dialogue' },
  dialogue: { insert: '\n\n', next: 'character' },
  transition: { insert: '\n\n', next: 'scene_heading' },
  centered: { insert: '\n\n', next: 'action' },
  lyric: { insert: '\n\n', next: 'action' },
};

export function stripMarkers(text) {
  let s = text.trim();
  if (s.startsWith('@') || s.startsWith('!') || s.startsWith('~')) s = s.slice(1);
  else if (s.startsWith('>')) s = s.slice(1).replace(/<\s*$/, '');
  else if (s.startsWith('.') && !s.startsWith('..')) s = s.slice(1);
  if (/^\(.*\)$/.test(s)) s = s.slice(1, -1);
  return s.trim();
}

export function applyType(text, type) {
  const s = stripMarkers(text);
  const u = s.toUpperCase();
  switch (type) {
    case 'character': return u;
    case 'parenthetical': return `(${s})`;
    case 'transition': return u.endsWith('TO:') ? u : `>${u}`;
    case 'scene_heading': return SCENE_PREFIX.test(u) ? u : `.${u}`;
    case 'centered': return `>${s}<`;
    case 'lyric': return `~${s}`;
    case 'action': return isUpperCue(s) || SCENE_PREFIX.test(s) ? `!${s}` : s;
    default: return s; // dialogue
  }
}

export function looksLikeCue(text) {
  const t = text.trim();
  return t.length > 0 && t.length <= 38 && isUpperCue(t) && !SCENE_PREFIX.test(t) && !t.endsWith('TO:');
}

export function nextInCycle(current, dir, allowParen) {
  if (current === 'dialogue' && allowParen) return dir > 0 ? 'parenthetical' : 'character';
  const order = CYCLE.filter((t) => t !== 'parenthetical' || allowParen);
  const idx = Math.max(0, order.indexOf(current ?? 'action'));
  return order[(idx + dir + order.length) % order.length];
}

const LEAD = { scene_heading: '.', character: '@', action: '!', transition: '>', centered: '>', lyric: '~', synopsis: '=', section: '#' };

export function markerRanges(text, type) {
  const r = [];
  const lead = text.length - text.trimStart().length;
  const t = text.trimStart();
  if (LEAD[type] && t[0] === LEAD[type] && !(type === 'scene_heading' && t[1] === '.')) r.push([lead, lead + 1, 'sw-marker']);
  if (type === 'centered' && text.trimEnd().endsWith('<')) {
    const e = text.trimEnd().length;
    r.push([e - 1, e, 'sw-marker']);
  }
  if (type === 'scene_heading') {
    const m = text.match(/#[A-Za-z0-9.-]+#\s*$/);
    if (m) r.push([m.index, m.index + m[0].trimEnd().length, 'sw-marker']);
  }
  if (type === 'character') {
    const m = text.match(/\^\s*$/);
    if (m) r.push([m.index, m.index + 1, 'sw-marker']);
  }
  for (const m of text.matchAll(/\[\[[\s\S]*?\]\]/g)) r.push([m.index, m.index + m[0].length, 'sw-note']);
  return r.sort((a, b) => a[0] - b[0]);
}
```

- [ ] **Step 3: Run the flow tests**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/editor/__tests__/flow.test.js
```
Expected: PASS.

- [ ] **Step 4: Write the failing command tests (CodeMirror state only, no DOM)**

`plugins/script-writer/src/editor/__tests__/commands.test.js`:
```js
import { EditorSelection, EditorState } from '@codemirror/state';
import { describe, expect, it } from 'vitest';
import { analysisField } from '../analysis.js';
import { cycleType, enter, setType, typeAt } from '../commands.js';
import { hintField } from '../hints.js';

const mk = (doc, cursor = doc.length) => EditorState.create({
  doc, selection: EditorSelection.cursor(cursor), extensions: [analysisField, hintField],
});
const run = (cmd, state) => {
  let next = state;
  const handled = cmd({ state, dispatch: (tr) => { next = tr.state; } });
  return { state: next, handled };
};
const doc = (s) => s.doc.toString();
const head = (s) => s.selection.main.head;

describe('Tab cycling', () => {
  it('turns a lowercase action line into an uppercase character', () => {
    const { state } = run(cycleType(1), mk('Go.\n\nmara'));
    expect(doc(state)).toBe('Go.\n\nMARA');
    expect(typeAt(state, 3)).toBe('character');
  });

  it('walks action → character → transition → scene heading → action outside dialogue', () => {
    let s = mk('night falls');
    const seen = [];
    for (let k = 0; k < 4; k++) { s = run(cycleType(1), s).state; seen.push([typeAt(s, 1), doc(s)]); }
    expect(seen).toEqual([
      ['character', 'NIGHT FALLS'],
      ['transition', '>NIGHT FALLS'],
      ['scene_heading', '.NIGHT FALLS'],
      ['action', '!NIGHT FALLS'],
    ]);
  });

  it('inserts () with the cursor inside on an empty line under a cue', () => {
    const start = run(enter, mk('MARA')).state; // → "MARA\n", dialogue hint
    const { state } = run(cycleType(1), start);
    expect(doc(state)).toBe('MARA\n()');
    expect(head(state)).toBe(6);
    expect(typeAt(state, 2)).toBe('parenthetical');
  });

  it('Mod-number sets a type directly', () => {
    const { state } = run(setType('transition'), mk('cut to:'));
    expect(doc(state)).toBe('CUT TO:');
  });
});

describe('Enter flow', () => {
  it('scene heading → blank line + action, uppercasing the heading', () => {
    const { state } = run(enter, mk('int. house - day'));
    expect(doc(state)).toBe('INT. HOUSE - DAY\n\n');
    expect(head(state)).toBe(18);
    expect(typeAt(state, 3)).toBe('action');
  });

  it('a cue-looking line → dialogue directly below, cue hinted as character', () => {
    const { state } = run(enter, mk('Go.\n\nMARA'));
    expect(doc(state)).toBe('Go.\n\nMARA\n');
    expect(typeAt(state, 3)).toBe('character');
    expect(typeAt(state, 4)).toBe('dialogue');
  });

  it('dialogue → blank line + character', () => {
    const { state } = run(enter, mk('MARA\nHello.'));
    expect(doc(state)).toBe('MARA\nHello.\n\n');
    expect(typeAt(state, 4)).toBe('character');
  });

  it('Enter on an empty hinted line resets it to action without inserting', () => {
    const afterDialogue = run(enter, mk('MARA\nHello.')).state;
    const { state, handled } = run(enter, afterDialogue);
    expect(handled).toBe(true);
    expect(doc(state)).toBe('MARA\nHello.\n\n');
    expect(typeAt(state, 4)).toBe('action');
  });

  it('Enter inside the closing paren of a parenthetical continues to dialogue', () => {
    const s = mk('MARA\n(quietly)', 'MARA\n(quietly'.length);
    const { state } = run(enter, s);
    expect(doc(state)).toBe('MARA\n(quietly)\n');
    expect(typeAt(state, 3)).toBe('dialogue');
  });

  it('falls through (returns false) mid-line and on plain empty lines', () => {
    expect(run(enter, mk('Hello there', 3)).handled).toBe(false);
    expect(run(enter, mk('Go.\n\n')).handled).toBe(false);
  });
});
```

- [ ] **Step 5: Run to verify they fail**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/editor/__tests__/commands.test.js
```
Expected: FAIL (modules not found).

- [ ] **Step 6: Implement `analysis.js`, `hints.js`, `commands.js`**

`plugins/script-writer/src/editor/analysis.js`:
```js
import { StateField } from '@codemirror/state';
import { parse } from '../fountain/parse.js';

export function analyze(text) {
  const elements = parse(text);
  const lineTypes = [];
  for (const el of elements) for (let l = el.line; l <= el.lineEnd; l++) lineTypes[l] = el.type;
  return { elements, lineTypes };
}

/** Whole-document parse, recomputed on every doc change (10k lines < 200ms). */
export const analysisField = StateField.define({
  create: (state) => analyze(state.doc.toString()),
  update: (value, tr) => (tr.docChanged ? analyze(tr.newDoc.toString()) : value),
});
```

`plugins/script-writer/src/editor/hints.js`:
```js
// Typed-element hints for lines Fountain can't classify yet (an empty line
// after a cue is "dialogue" before any text exists). Hints live only on the
// cursor line and the line above it; everywhere else the parse is the truth.
import { StateEffect, StateField } from '@codemirror/state';

export const setHint = StateEffect.define();

export const hintField = StateField.define({
  create: () => [],
  update(hints, tr) {
    const doc = tr.newDoc;
    let next = hints.map((h) => ({ ...h, pos: tr.changes.mapPos(h.pos, -1) }));
    for (const e of tr.effects) {
      if (!e.is(setHint)) continue;
      const line = doc.lineAt(e.value.pos);
      next = next.filter((h) => doc.lineAt(h.pos).number !== line.number).concat({ pos: line.from, type: e.value.type });
    }
    const cur = doc.lineAt(tr.newSelection.main.head).number;
    return next.filter((h) => {
      const n = doc.lineAt(h.pos).number;
      return n === cur || n === cur - 1;
    });
  },
});

export function hintAt(state, lineNo) {
  const line = state.doc.line(lineNo);
  const h = (state.field(hintField, false) ?? []).find((x) => x.pos >= line.from && x.pos <= line.to);
  return h?.type ?? null;
}
```

`plugins/script-writer/src/editor/commands.js`:
```js
import { EditorSelection } from '@codemirror/state';
import { analysisField } from './analysis.js';
import { CAPS_TYPES, NEXT_ON_ENTER, applyType, looksLikeCue, nextInCycle } from './flow.js';
import { hintAt, setHint } from './hints.js';

export function typeAt(state, lineNo) {
  if (lineNo < 1 || lineNo > state.doc.lines) return null;
  return hintAt(state, lineNo) ?? state.field(analysisField).lineTypes[lineNo - 1] ?? null;
}

const isBlankLine = (state, n) => n < 1 || n > state.doc.lines || state.doc.line(n).text.trim() === '';

function retype(state, line, type) {
  const empty = line.text.trim() === '';
  const insert = empty ? (type === 'parenthetical' ? '()' : '') : applyType(line.text, type);
  const cursor = line.from + (type === 'parenthetical' ? insert.length - 1 : insert.length);
  return state.update({
    changes: { from: line.from, to: line.to, insert },
    selection: EditorSelection.cursor(cursor),
    effects: setHint.of({ pos: line.from, type }),
    userEvent: 'input.type',
  });
}

export const cycleType = (dir) => ({ state, dispatch }) => {
  const line = state.doc.lineAt(state.selection.main.head);
  const cur = typeAt(state, line.number);
  const prev = isBlankLine(state, line.number - 1) ? null : typeAt(state, line.number - 1);
  const allowParen = ['character', 'dialogue', 'parenthetical'].includes(prev) || cur === 'dialogue';
  dispatch(retype(state, line, nextInCycle(cur, dir, allowParen)));
  return true;
};

export const setType = (type) => ({ state, dispatch }) => {
  dispatch(retype(state, state.doc.lineAt(state.selection.main.head), type));
  return true;
};

export function enter({ state, dispatch }) {
  const sel = state.selection.main;
  if (!sel.empty) return false;
  const line = state.doc.lineAt(sel.head);
  const after = line.text.slice(sel.head - line.from);
  if (after !== '' && after.trim() !== ')') return false; // mid-line: default newline
  if (line.text.trim() === '') {
    const h = hintAt(state, line.number);
    if (!h || h === 'action') return false;
    dispatch(state.update({ effects: setHint.of({ pos: line.from, type: 'action' }) }));
    return true;
  }
  let type = typeAt(state, line.number) ?? 'action';
  if (type === 'action' && isBlankLine(state, line.number - 1) && looksLikeCue(line.text)) type = 'character';
  const rule = NEXT_ON_ENTER[type] ?? NEXT_ON_ENTER.action;
  const text = CAPS_TYPES.has(type) ? line.text.toUpperCase() : line.text;
  const pos = line.from + text.length + rule.insert.length;
  const effects = [setHint.of({ pos, type: rule.next })];
  if (type === 'character') effects.push(setHint.of({ pos: line.from, type: 'character' }));
  dispatch(state.update({
    changes: { from: line.from, to: line.to, insert: text + rule.insert },
    selection: EditorSelection.cursor(pos),
    effects,
    scrollIntoView: true,
    userEvent: 'input',
  }));
  return true;
}
```

- [ ] **Step 7: Run all editor tests**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/editor
```
Expected: PASS. If a hint test fails because the hint was dropped, check `hintField`'s cursor-line filter. It uses `tr.newSelection` and needs the commands to pass `selection` in the same transaction as the effect, which they do.

- [ ] **Step 8: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer/src/editor && git commit -m "feat(script-writer): Final Draft-style element flow (Tab/Enter/hints)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Autocomplete

**Files:**
- Create: `plugins/script-writer/src/editor/completions.js`, `plugins/script-writer/src/editor/complete.js`
- Test: `plugins/script-writer/src/editor/__tests__/completions.test.js`

**Interfaces:**
- Consumes: `characters` (Task 6), `typeAt` and `analysisField` (Task 7).
- Produces:
  - `PREFIXES`, `TIMES`, `EXTENSIONS`, `locations(elements) → string[]`.
  - `completionsFor({text, type, prevBlank, elements}) → {from, options: string[]} | null`. `text` is the line up to the cursor, and `from` is the offset within the line.
  - `scriptCompletions() → Extension`.

- [ ] **Step 1: Write the failing tests**

`plugins/script-writer/src/editor/__tests__/completions.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { parse } from '../../fountain/parse.js';
import { completionsFor, locations } from '../completions.js';

const els = parse('INT. LIGHTHOUSE - NIGHT\n\nMARA\nHi.\n\nEXT. BEACH - DAY\n\nJOE\nYo.\n\nMARA\nAgain.\n\nINT. LIGHTHOUSE - DAY\n\nGo.');
const c = (text, type = 'action', prevBlank = true) => completionsFor({ text, type, prevBlank, elements: els });

describe('completions', () => {
  it('ranks locations by use', () => {
    expect(locations(els)).toEqual(['LIGHTHOUSE', 'BEACH']);
  });
  it('offers scene prefixes for a short start on a fresh line', () => {
    expect(c('in')).toEqual({ from: 0, options: ['INT. ', 'INT./EXT. '] });
    expect(c('INT.')).toEqual({ from: 0, options: ['INT. ', 'INT./EXT. '] });
  });
  it('offers known locations after the prefix', () => {
    expect(c('INT. LI', 'scene_heading')).toEqual({ from: 5, options: ['LIGHTHOUSE'] });
  });
  it('offers times after " - "', () => {
    expect(c('INT. LIGHTHOUSE - N', 'scene_heading')).toEqual({ from: 18, options: ['NIGHT'] });
  });
  it('offers character names by frequency', () => {
    expect(c('', 'character')).toEqual({ from: 0, options: ['MARA', 'JOE'] });
    expect(c('J', 'character')).toEqual({ from: 0, options: ['JOE'] });
  });
  it('offers extensions after (', () => {
    expect(c('MARA (', 'character').options).toEqual(['(V.O.)', '(O.S.)', "(CONT'D)", '(O.C.)']);
    expect(c('MARA (V', 'character')).toEqual({ from: 5, options: ['(V.O.)'] });
  });
  it('offers nothing inside dialogue or mid-paragraph', () => {
    expect(c('hel', 'dialogue', false)).toBeNull();
    expect(c('She walks', 'action', false)).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/editor/__tests__/completions.test.js
```
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `completions.js`**

`plugins/script-writer/src/editor/completions.js`:
```js
import { characters } from '../fountain/outline.js';

export const PREFIXES = ['INT. ', 'EXT. ', 'INT./EXT. ', 'I/E. '];
export const TIMES = ['DAY', 'NIGHT', 'CONTINUOUS', 'LATER', 'MOMENTS LATER', 'MORNING', 'EVENING'];
export const EXTENSIONS = ['(V.O.)', '(O.S.)', "(CONT'D)", '(O.C.)'];
const HEAD = /^(INT\.?\/EXT\.?|EXT\.?\/INT\.?|INT\/EXT\.?|I\/E\.?|INT\.?|EXT\.?|EST\.?)\s+/i;

export function locations(elements) {
  const counts = new Map();
  for (const el of elements) {
    if (el.type !== 'scene_heading') continue;
    const loc = el.text.replace(HEAD, '').split(' - ')[0].trim().toUpperCase();
    if (loc) counts.set(loc, (counts.get(loc) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([l]) => l);
}

function filtered(list, typed, from) {
  const u = typed.toUpperCase();
  const options = list.filter((o) => o.toUpperCase().startsWith(u) && o.toUpperCase() !== u);
  return options.length ? { from, options } : null;
}

export function completionsFor({ text, type, prevBlank, elements }) {
  if (type === 'dialogue' || type === 'parenthetical') return null;
  const head = text.match(HEAD);
  if (head && (type === 'scene_heading' || prevBlank)) {
    const rest = text.slice(head[0].length);
    const dash = rest.lastIndexOf(' - ');
    if (dash >= 0) {
      const from = head[0].length + dash + 3;
      return filtered(TIMES, text.slice(from), from);
    }
    return filtered(locations(elements), rest, head[0].length);
  }
  if (prevBlank && /^[a-z./]{1,9}$/i.test(text)) {
    const r = filtered(PREFIXES, text, 0);
    if (r) return r;
  }
  if (type === 'character' || (prevBlank && /^[A-Z][A-Z0-9 .'’-]*$/.test(text))) {
    const paren = text.lastIndexOf('(');
    if (paren >= 0) return filtered(EXTENSIONS, text.slice(paren), paren);
    return filtered(characters(elements).map((ch) => ch.name), text.trim(), 0);
  }
  return null;
}
```

- [ ] **Step 4: Implement the CodeMirror source `complete.js`**

`plugins/script-writer/src/editor/complete.js`:
```js
import { autocompletion } from '@codemirror/autocomplete';
import { analysisField } from './analysis.js';
import { typeAt } from './commands.js';
import { completionsFor } from './completions.js';

export function scriptCompletions() {
  return autocompletion({
    icons: false,
    activateOnTyping: true,
    override: [(ctx) => {
      const line = ctx.state.doc.lineAt(ctx.pos);
      const text = line.text.slice(0, ctx.pos - line.from);
      const type = typeAt(ctx.state, line.number);
      if (!text.trim() && !ctx.explicit && type !== 'character') return null;
      const prevBlank = line.number === 1 || ctx.state.doc.line(line.number - 1).text.trim() === '';
      const r = completionsFor({ text, type, prevBlank, elements: ctx.state.field(analysisField).elements });
      if (!r) return null;
      return { from: line.from + r.from, options: r.options.map((label) => ({ label, type: 'text' })) };
    }],
  });
}
```

- [ ] **Step 5: Run tests**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/editor
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer/src/editor && git commit -m "feat(script-writer): screenplay autocomplete (prefixes, locations, times, cues)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Library registry and resilient saver

**Files:**
- Create: `plugins/script-writer/src/store/registry.js`, `plugins/script-writer/src/store/saver.js`
- Test: `plugins/script-writer/src/store/__tests__/registry.test.js`, `plugins/script-writer/src/store/__tests__/saver.test.js`

**Interfaces:**
- Consumes: `parseScriptPath` (Task 3).
- Produces:
  - `Entry = {path, title, context, project, updated, pages, missing?}`.
  - `loadRegistry(settings) → Entry[]`, `upsertEntry(settings, entry) → Entry[]`, `removeEntry(settings, path) → Entry[]`, and `markMissing(settings, path) → Entry[]`.
  - `entryFor(path, meta, pages) → Entry`.
  - `BACKOFF_MS` and `createSaver({save, mirror, onStatus, delayMs?}) → {change(content), flush(): Promise, dispose(), status}`, with statuses `saved | dirty | saving | error`.
  - `shouldOfferDraft(draft, meta, body) → boolean`.

- [ ] **Step 1: Write the failing tests**

`plugins/script-writer/src/store/__tests__/registry.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { entryFor, loadRegistry, markMissing, removeEntry, upsertEntry } from '../registry.js';

const memSettings = (init) => {
  const m = new Map(Object.entries(init ?? {}));
  return { get: async (k) => m.get(k), set: async (k, v) => { m.set(k, v); } };
};
const P = '20-contexts/personal/projects/night/draft.screenplay.md';

describe('registry', () => {
  it('starts empty and tolerates garbage', async () => {
    expect(await loadRegistry(memSettings())).toEqual([]);
    expect(await loadRegistry(memSettings({ scripts: 'nope' }))).toEqual([]);
  });
  it('upserts most-recent-first without duplicates, and clears missing', async () => {
    const s = memSettings();
    await upsertEntry(s, { path: 'a', title: 'A' });
    await upsertEntry(s, { path: 'b', title: 'B' });
    await markMissing(s, 'a');
    expect((await loadRegistry(s)).find((e) => e.path === 'a').missing).toBe(true);
    const list = await upsertEntry(s, { path: 'a', title: 'A2' });
    expect(list.map((e) => [e.path, e.title, e.missing])).toEqual([['a', 'A2', undefined], ['b', 'B', undefined]]);
  });
  it('removes entries', async () => {
    const s = memSettings({ scripts: [{ path: 'a' }, { path: 'b' }] });
    expect(await removeEntry(s, 'a')).toEqual([{ path: 'b' }]);
  });
  it('builds entries from path + meta', () => {
    expect(entryFor(P, { title: 'Night', updated: 'T' }, 3)).toEqual({
      path: P, title: 'Night', context: 'personal', project: 'night', updated: 'T', pages: 3,
    });
  });
});
```

`plugins/script-writer/src/store/__tests__/saver.test.js`:
```js
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createSaver, shouldOfferDraft } from '../saver.js';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function harness(saveImpl) {
  const saved = [];
  const mirrored = [];
  const statuses = [];
  const saver = createSaver({
    save: vi.fn(async (c) => { await saveImpl(c); saved.push(c); }),
    mirror: vi.fn(async (c) => { mirrored.push(c); }),
    onStatus: (s, info) => statuses.push(info ? [s, info.retryInMs] : s),
  });
  return { saver, saved, mirrored, statuses };
}

describe('saver', () => {
  it('debounces to one save of the latest content', async () => {
    const h = harness(async () => {});
    h.saver.change('a');
    await vi.advanceTimersByTimeAsync(1000);
    h.saver.change('ab');
    await vi.advanceTimersByTimeAsync(1499);
    expect(h.saved).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.saved).toEqual(['ab']);
    expect(h.statuses).toEqual(['dirty', 'dirty', 'saving', 'saved']);
  });

  it('on failure mirrors, backs off 2s then 4s, and saves the newest text', async () => {
    let fails = 2;
    const h = harness(async () => { if (fails-- > 0) throw new Error('sidecar down'); });
    h.saver.change('v1');
    await vi.advanceTimersByTimeAsync(1500);
    expect(h.statuses.at(-1)).toEqual(['error', 2000]);
    expect(h.mirrored).toEqual(['v1']);
    h.saver.change('v2'); // typing during an outage keeps the backoff schedule
    await vi.advanceTimersByTimeAsync(2000);
    expect(h.statuses.at(-1)).toEqual(['error', 4000]);
    expect(h.mirrored.at(-1)).toBe('v2');
    await vi.advanceTimersByTimeAsync(4000);
    expect(h.saved).toEqual(['v2']);
    expect(h.statuses.at(-1)).toBe('saved');
  });

  it('flush saves immediately and dispose stops retries', async () => {
    const h = harness(async () => {});
    h.saver.change('x');
    await h.saver.flush();
    expect(h.saved).toEqual(['x']);
    const bad = harness(async () => { throw new Error('no'); });
    bad.saver.change('y');
    await bad.saver.flush();
    bad.saver.dispose();
    await vi.advanceTimersByTimeAsync(60000);
    expect(bad.saver.status).toBe('error');
    expect(bad.mirrored).toEqual(['y']);
  });
});

describe('shouldOfferDraft', () => {
  it('offers only a newer, different draft', () => {
    const meta = { updated: '2026-09-30T10:00:00.000Z' };
    expect(shouldOfferDraft(null, meta, 'a')).toBe(false);
    expect(shouldOfferDraft({ content: 'a', savedAt: '2026-09-30T11:00:00.000Z' }, meta, 'a')).toBe(false);
    expect(shouldOfferDraft({ content: 'b', savedAt: '2026-09-30T09:00:00.000Z' }, meta, 'a')).toBe(false);
    expect(shouldOfferDraft({ content: 'b', savedAt: '2026-09-30T11:00:00.000Z' }, meta, 'a')).toBe(true);
    expect(shouldOfferDraft({ content: 'b', savedAt: '2026-09-30T11:00:00.000Z' }, { updated: '' }, 'a')).toBe(true);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/store
```
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement `registry.js`**

`plugins/script-writer/src/store/registry.js`:
```js
// Library registry in plugin settings (no list-by-folder API exists).
import { parseScriptPath } from '../fountain/document.js';

const KEY = 'scripts';

export async function loadRegistry(settings) {
  const v = await settings.get(KEY);
  return Array.isArray(v) ? v : [];
}

export async function upsertEntry(settings, entry) {
  const { missing, ...clean } = entry;
  const list = [clean, ...(await loadRegistry(settings)).filter((e) => e.path !== entry.path)];
  await settings.set(KEY, list);
  return list;
}

export async function removeEntry(settings, path) {
  const list = (await loadRegistry(settings)).filter((e) => e.path !== path);
  await settings.set(KEY, list);
  return list;
}

export async function markMissing(settings, path) {
  const list = (await loadRegistry(settings)).map((e) => (e.path === path ? { ...e, missing: true } : e));
  await settings.set(KEY, list);
  return list;
}

export function entryFor(path, meta, pages) {
  const p = parseScriptPath(path) ?? { context: '', project: '' };
  return { path, title: meta.title, context: p.context, project: p.project, updated: meta.updated, pages };
}
```

- [ ] **Step 4: Implement `saver.js`**

`plugins/script-writer/src/store/saver.js`:
```js
// Debounced autosave that never drops text: failures retry with backoff and
// the latest unsaved content is mirrored to the plugin data dir.
export const BACKOFF_MS = [2000, 4000, 8000, 16000, 30000];

export function createSaver({ save, mirror, onStatus = () => {}, delayMs = 1500 }) {
  let pending = null;
  let timer = null;
  let inflight = null;
  let attempt = 0;
  let disposed = false;
  let status = 'saved';
  const setStatus = (s, info) => { status = s; onStatus(s, info); };
  const schedule = (ms) => { clearTimeout(timer); timer = setTimeout(run, ms); };

  function run() {
    timer = null;
    if (pending === null || inflight) return inflight ?? Promise.resolve();
    const content = pending;
    pending = null;
    setStatus('saving');
    inflight = (async () => {
      try {
        await save(content);
        attempt = 0;
        if (pending === null) setStatus('saved');
        else if (!disposed) schedule(delayMs);
      } catch (err) {
        if (pending === null) pending = content;
        const wait = BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
        attempt++;
        setStatus('error', { message: err?.message ?? String(err), retryInMs: wait });
        try { await mirror(pending); } catch { /* best effort: the editor still holds the text */ }
        if (!disposed) schedule(wait);
      } finally {
        inflight = null;
      }
    })();
    return inflight;
  }

  return {
    change(content) {
      pending = content;
      if (status === 'error') return; // keep the backoff schedule during an outage
      setStatus('dirty');
      schedule(delayMs);
    },
    async flush() {
      clearTimeout(timer);
      timer = null;
      if (inflight) await inflight;
      if (pending !== null) await run();
    },
    dispose() {
      disposed = true;
      clearTimeout(timer);
    },
    get status() { return status; },
  };
}

export function shouldOfferDraft(draft, meta, body) {
  if (!draft || typeof draft.content !== 'string' || draft.content === body) return false;
  return String(draft.savedAt ?? '') > String(meta?.updated ?? '');
}
```

- [ ] **Step 5: Run tests**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/store
```
Expected: PASS. If the "typing during an outage" test fails, check the ordering. The retry at 2000ms must save `v2`, which is `pending` because `change()` updated it. That save fails and schedules 4000ms, and `mirror` receives `v2`.

- [ ] **Step 6: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer/src/store && git commit -m "feat(script-writer): library registry + backoff saver with draft mirror

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Main process (drafts, import/export, PDF)

**Files:**
- Create: `plugins/script-writer/src/main/drafts.js`, `plugins/script-writer/src/main/files.js`
- Modify: `plugins/script-writer/src/main.js` (replace the stub)
- Test: `plugins/script-writer/src/main/__tests__/drafts.test.js`, `plugins/script-writer/src/main/__tests__/files.test.js`

**Interfaces:**
- Consumes: `FONT_PLACEHOLDER` and `FONT_FILES` (Task 5).
- Produces these IPC channels. Renderer calls are `plugin.ipc.invoke(channel, arg)`.
  - `draft-write`: arg `{key, content, savedAt}`, returns `true`.
  - `draft-read`: arg `key`, returns `{content, savedAt} | null`.
  - `draft-clear`: arg `key`, returns `true`.
  - `export-file`: arg `{defaultName, ext: 'fountain'|'txt', content}`, returns `{path} | {canceled: true}`.
  - `import-file`: no arg, returns `{name, content} | {canceled: true}`.
  - `export-pdf`: arg `{html, defaultName, paper}`, returns `{path} | {canceled: true}`.

- [ ] **Step 1: Write the failing tests**

`plugins/script-writer/src/main/__tests__/drafts.test.js`:
```js
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { clearDraft, readDraft, writeDraft } from '../drafts.js';

const dir = () => mkdtempSync(join(tmpdir(), 'sw-drafts-'));

describe('drafts', () => {
  it('writes, reads and clears a draft', () => {
    const d = dir();
    expect(readDraft(d, 'a-b')).toBeNull();
    writeDraft(d, { key: 'a-b', content: 'FADE IN:', savedAt: 'T' });
    expect(readDraft(d, 'a-b')).toEqual({ content: 'FADE IN:', savedAt: 'T' });
    clearDraft(d, 'a-b');
    expect(readDraft(d, 'a-b')).toBeNull();
  });
  it('rejects unsafe keys and non-string content', () => {
    const d = dir();
    expect(() => writeDraft(d, { key: '../etc', content: 'x' })).toThrow(/invalid draft key/);
    expect(() => writeDraft(d, { key: 'ok', content: 5 })).toThrow(/content/);
  });
  it('treats a corrupt draft as absent', () => {
    const d = dir();
    mkdirSync(join(d, 'drafts'));
    writeFileSync(join(d, 'drafts', 'bad.json'), '{nope');
    expect(readDraft(d, 'bad')).toBeNull();
  });
});
```

`plugins/script-writer/src/main/__tests__/files.test.js`:
```js
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { FONT_FILES } from '../../render/pageHtml.js';
import { exportName, inlineFonts } from '../files.js';

describe('files', () => {
  it('builds safe export names', () => {
    expect(exportName('my/script:v2', 'pdf')).toBe('my-script-v2.pdf');
    expect(exportName('', 'fountain')).toBe('screenplay.fountain');
    expect(exportName('a.PDF', 'pdf')).toBe('a.PDF');
  });
  it('inlines font placeholders as data URLs and rejects unknown files', () => {
    const d = mkdtempSync(join(tmpdir(), 'sw-fonts-'));
    for (const f of FONT_FILES) writeFileSync(join(d, f), 'woff');
    const out = inlineFonts(`url("__FONT_BASE__${FONT_FILES[0]}")`, d);
    expect(out).toBe(`url("data:font/woff2;base64,${Buffer.from('woff').toString('base64')}")`);
    expect(() => inlineFonts('url("__FONT_BASE__../x.woff2")', d)).toThrow(/unknown font/);
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/main
```
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement `drafts.js` and `files.js`**

`plugins/script-writer/src/main/drafts.js`:
```js
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const KEY = /^[a-z0-9-]{1,120}$/;

function draftFile(dataDir, key) {
  if (!KEY.test(String(key))) throw new Error(`invalid draft key: ${JSON.stringify(key)}`);
  return join(dataDir, 'drafts', `${key}.json`);
}

export function writeDraft(dataDir, { key, content, savedAt }) {
  const file = draftFile(dataDir, key);
  if (typeof content !== 'string') throw new Error('draft content must be a string');
  mkdirSync(join(dataDir, 'drafts'), { recursive: true });
  writeFileSync(file, JSON.stringify({ content, savedAt: String(savedAt ?? '') }));
  return true;
}

export function readDraft(dataDir, key) {
  const file = draftFile(dataDir, key);
  try {
    return JSON.parse(readFileSync(file, 'utf-8'));
  } catch (e) {
    if (e.code === 'ENOENT' || e instanceof SyntaxError) return null;
    throw e;
  }
}

export function clearDraft(dataDir, key) {
  rmSync(draftFile(dataDir, key), { force: true });
  return true;
}
```

`plugins/script-writer/src/main/files.js`:
```js
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { FONT_FILES, FONT_PLACEHOLDER } from '../render/pageHtml.js';

export const IMPORT_EXTS = ['fountain', 'spmd', 'txt'];
export const EXPORT_EXTS = ['fountain', 'txt'];
export const MAX_IMPORT_BYTES = 5 * 1024 * 1024;

export function exportName(name, ext) {
  const base = String(name ?? '').replace(/[\\/:*?"<>|]+/g, '-').trim() || 'screenplay';
  return base.toLowerCase().endsWith(`.${ext}`) ? base : `${base}.${ext}`;
}

/** Replace __FONT_BASE__<file> with data: URLs so the hidden print window needs no file:// font access. */
export function inlineFonts(html, fontDir) {
  const re = new RegExp(`${FONT_PLACEHOLDER}([^"')\\s]+)`, 'g');
  return html.replace(re, (_, name) => {
    if (!FONT_FILES.includes(name)) throw new Error(`unknown font: ${name}`);
    return `data:font/woff2;base64,${readFileSync(join(fontDir, name)).toString('base64')}`;
  });
}
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/main
```
Expected: PASS.

- [ ] **Step 5: Replace `src/main.js` with the real handlers**

`plugins/script-writer/src/main.js`:
```js
// Main-process entry: drafts in dataDir, file dialogs, and PDF printing
// through a hidden BrowserWindow. Renderer owns all vault I/O.
import { BrowserWindow, dialog } from 'electron';
import { mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { basename, join } from 'node:path';
import { clearDraft, readDraft, writeDraft } from './main/drafts.js';
import { EXPORT_EXTS, IMPORT_EXTS, MAX_IMPORT_BYTES, exportName, inlineFonts } from './main/files.js';

let ctx = null;
const printWindows = new Set();

const withParent = (fn, opts) => {
  const parent = BrowserWindow.getFocusedWindow();
  return parent ? fn(parent, opts) : fn(opts);
};

async function exportFile(req) {
  const { defaultName, ext, content } = req ?? {};
  if (!EXPORT_EXTS.includes(ext)) throw new Error(`export-file: unsupported extension ${JSON.stringify(ext)}`);
  if (typeof content !== 'string') throw new Error('export-file: content must be a string');
  const r = await withParent(dialog.showSaveDialog.bind(dialog), {
    defaultPath: exportName(defaultName, ext), filters: [{ name: ext === 'fountain' ? 'Fountain' : 'Text', extensions: [ext] }],
  });
  if (r.canceled || !r.filePath) return { canceled: true };
  writeFileSync(r.filePath, content, 'utf-8');
  return { path: r.filePath };
}

async function importFile() {
  const r = await withParent(dialog.showOpenDialog.bind(dialog), {
    properties: ['openFile'], filters: [{ name: 'Screenplay', extensions: IMPORT_EXTS }],
  });
  if (r.canceled || !r.filePaths?.length) return { canceled: true };
  const file = r.filePaths[0];
  if (statSync(file).size > MAX_IMPORT_BYTES) throw new Error(`${basename(file)} is larger than 5 MB`);
  return { name: basename(file), content: readFileSync(file, 'utf-8') };
}

async function exportPdf(req) {
  const { html, defaultName, paper } = req ?? {};
  if (typeof html !== 'string' || !html.startsWith('<!doctype html>')) throw new Error('export-pdf: expected an html document');
  const r = await withParent(dialog.showSaveDialog.bind(dialog), {
    defaultPath: exportName(defaultName, 'pdf'), filters: [{ name: 'PDF', extensions: ['pdf'] }],
  });
  if (r.canceled || !r.filePath) return { canceled: true };
  const tmpDir = join(ctx.dataDir, 'tmp');
  mkdirSync(tmpDir, { recursive: true });
  const tmp = join(tmpDir, `print-${Date.now()}.html`);
  writeFileSync(tmp, inlineFonts(html, join(ctx.pluginDir, 'dist', 'fonts')), 'utf-8');
  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true } });
  printWindows.add(win);
  try {
    await win.loadFile(tmp);
    await win.webContents.executeJavaScript('document.fonts.ready.then(() => true)');
    const pdf = await win.webContents.printToPDF({
      pageSize: paper === 'a4' ? 'A4' : 'Letter',
      printBackground: true,
      preferCSSPageSize: true,
      margins: { marginType: 'none' },
    });
    writeFileSync(r.filePath, pdf);
    return { path: r.filePath };
  } finally {
    printWindows.delete(win);
    if (!win.isDestroyed()) win.destroy();
    rmSync(tmp, { force: true });
  }
}

export function activate(context) {
  ctx = context;
  ctx.ipc.handle('draft-write', (req) => writeDraft(ctx.dataDir, req ?? {}));
  ctx.ipc.handle('draft-read', (key) => readDraft(ctx.dataDir, key));
  ctx.ipc.handle('draft-clear', (key) => clearDraft(ctx.dataDir, key));
  ctx.ipc.handle('export-file', exportFile);
  ctx.ipc.handle('import-file', importFile);
  ctx.ipc.handle('export-pdf', exportPdf);
  ctx.log('activated');
}

export function deactivate() {
  for (const w of printWindows) if (!w.isDestroyed()) w.destroy();
  printWindows.clear();
  ctx = null;
}
```

- [ ] **Step 6: Build to check the main bundle**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npm run build && node -e "const m=require('./dist/main.cjs');console.log(typeof m.activate, typeof m.deactivate)" 2>&1 | tail -1
```
Expected: `function function`. If `require('electron')` throws outside Electron, expect `Cannot find module 'electron'` instead. That's fine too: it proves `electron` stayed external. Either outcome is acceptable, and anything else is a bundling bug.

- [ ] **Step 7: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer/src && git commit -m "feat(script-writer): main-process drafts, import/export, PDF printing

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: UI shell (styles, mount, library, new-script dialog)

**Files:**
- Create: `plugins/script-writer/src/ui/styles.js`, `App.jsx`, `Library.jsx`, `NewScriptDialog.jsx`, `TitlePageFields.jsx`, `useUiSettings.js`
- Modify: `plugins/script-writer/src/renderer.jsx` (replace the stub)
- Test: `plugins/script-writer/src/ui/__tests__/mount.test.jsx`

**Interfaces:**
- Consumes: Task 3 (`backend`, `document`), Task 5 (`fontFaceCss`, `pageCss`), and Task 9 (`registry`).
- Produces:
  - `mount(el, plugin) → unmount`.
  - `appCss() → string`.
  - `useUiSettings(plugin) → [ui, patchUi]`, where `ui = {sceneNav, panel: 'page'|null, dark, paper, focus, sceneNumbersDefault}`.
  - `<TitlePageFields value onChange/>` and `<NewScriptDialog plugin initial? onCreate(path) onCancel/>`.
  - `<Library plugin onOpen(path) notify/>` and `<App plugin/>`.
  - `EditorScreen` is imported from Task 12. Until then, `App` imports a placeholder at the same path, created in this task.

- [ ] **Step 1: Write the failing smoke test**

`plugins/script-writer/src/ui/__tests__/mount.test.jsx`:
```jsx
// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { mount } from '../../renderer.jsx';

const tick = () => new Promise((r) => setTimeout(r, 20));

function fakePlugin(scripts = []) {
  const store = new Map([['scripts', scripts]]);
  return {
    pluginId: 'script-writer',
    theme: { '--paper': '#101010', '--ink-0': '#eee' },
    settings: { get: async (k) => store.get(k), set: async (k, v) => { store.set(k, v); } },
    api: { fetch: async () => ({ ok: true, data: [] }) },
    ipc: { invoke: async () => null, on: () => () => {} },
    openExternal: () => {},
  };
}

describe('mount', () => {
  it('renders the library with registry entries and unmounts cleanly', async () => {
    const el = document.createElement('div');
    const unmount = mount(el, fakePlugin([{ path: '20-contexts/personal/projects/n/a.screenplay.md', title: 'The Long Night', context: 'personal', project: 'n', updated: '2026-09-30T10:00:00Z', pages: 97 }]));
    await tick();
    expect(el.textContent).toContain('The Long Night');
    expect(el.textContent).toContain('97 pp');
    expect(el.style.getPropertyValue('--paper')).toBe('#101010');
    unmount();
    expect(el.childNodes.length).toBe(0);
  });

  it('shows an empty state', async () => {
    const el = document.createElement('div');
    const unmount = mount(el, fakePlugin());
    await tick();
    expect(el.textContent).toContain('No scripts yet');
    unmount();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/ui
```
Expected: FAIL, because the stub renders "Script Writer" with no library.

- [ ] **Step 3: Implement `styles.js` and `useUiSettings.js`**

`plugins/script-writer/src/ui/styles.js`:
```js
import { fontFaceCss } from '../render/pageHtml.js';

const fontBase = () => {
  try { return new URL('./fonts/', import.meta.url).href; } catch { return './fonts/'; }
};

export function appCss() {
  return `${fontFaceCss(fontBase())}
.sw-root{height:100%;display:flex;flex-direction:column;position:relative;color:var(--ink-0,#e8e6e3);background:var(--paper,#121212);font:13px/1.45 system-ui,-apple-system,sans-serif}
.sw-bar{display:flex;align-items:center;gap:6px;padding:8px 12px;border-bottom:1px solid var(--hairline,#2a2a2a);flex-wrap:wrap}
.sw-bar .sw-grow{flex:1;min-width:8px}
.sw-btn{display:inline-flex;align-items:center;gap:6px;padding:5px 10px;border-radius:6px;border:1px solid var(--hairline,#2a2a2a);background:var(--vellum,#1a1a1a);color:inherit;cursor:pointer;font:inherit}
.sw-btn:hover{border-color:var(--ink-2,#666)}
.sw-btn.sw-on{border-color:var(--neon,#b8f25c);color:var(--neon,#b8f25c)}
.sw-btn.sw-primary{background:var(--neon,#b8f25c);color:#111;border-color:transparent}
.sw-muted{color:var(--ink-2,#888)}
.sw-title{font-weight:600;cursor:pointer}
.sw-status{font-size:12px;color:var(--ink-2,#888)}.sw-status.sw-err{color:var(--oxblood,#e06c75)}
.sw-body{flex:1;display:flex;min-height:0}
.sw-side{width:240px;flex:none;overflow:auto;border-right:1px solid var(--hairline,#2a2a2a);padding:8px 0}
.sw-h{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-2,#888);padding:8px 12px 4px}
.sw-scene{padding:5px 12px;cursor:pointer;border-left:2px solid transparent}
.sw-scene:hover{background:var(--vellum,#1a1a1a)}
.sw-scene.sw-active{border-left-color:var(--neon,#b8f25c);background:var(--vellum,#1a1a1a)}
.sw-scene.sw-over{box-shadow:inset 0 2px 0 var(--neon,#b8f25c)}
.sw-num{display:inline-block;min-width:24px;color:var(--ink-2,#888);font-variant-numeric:tabular-nums}
.sw-syn{font-size:12px;color:var(--ink-2,#888);margin-left:24px}
.sw-char{display:flex;justify-content:space-between;padding:4px 12px;cursor:pointer}.sw-char:hover{background:var(--vellum,#1a1a1a)}
.sw-main{flex:1;overflow:auto;background:var(--fog,#0c0c0c)}
.sw-right{width:460px;flex:none;overflow:auto;border-left:1px solid var(--hairline,#2a2a2a);background:var(--fog,#0c0c0c)}
.sw-sheet{width:8.5in;min-height:11in;margin:24px auto 64px;background:#fff;color:#111;box-shadow:0 2px 24px rgba(0,0,0,.35)}
.sw-dark .sw-sheet{background:#1d1c1a;color:#e9e4da}
.sw-sheet .cm-editor{font-family:'Courier Prime','Courier New',monospace;font-size:12pt;outline:none}
.sw-sheet .cm-editor.cm-focused{outline:none}
.sw-sheet .cm-content{padding:1in 1in 1in 1.5in;caret-color:currentColor}
.sw-sheet .cm-line{line-height:.1667in;padding:0!important}
.sw-sheet .cm-cursor{border-left-color:currentColor}
.sw-l-scene_heading{font-weight:700}
.sw-l-character{padding-left:2.2in!important}
.sw-l-parenthetical{padding-left:1.6in!important;padding-right:1.9in!important}
.sw-l-dialogue{padding-left:1.0in!important;padding-right:1.5in!important}
.sw-l-transition{text-align:right}
.sw-l-centered{text-align:center}
.sw-l-lyric{font-style:italic}
.sw-l-note,.sw-l-section,.sw-l-synopsis,.sw-l-boneyard,.sw-note{color:#8a8a8a}
.sw-l-section{font-weight:700}
.sw-marker{opacity:.35}
.sw-dim{opacity:.28;transition:opacity .15s}
.sw-pagewrap{padding:16px}
.sw-pagewrap .sw-page{margin:0 auto 16px;box-shadow:0 1px 12px rgba(0,0,0,.4)}
.sw-lib{padding:24px;overflow:auto}
.sw-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;margin-top:16px}
.sw-card{padding:14px;border:1px solid var(--hairline,#2a2a2a);border-radius:10px;background:var(--vellum,#1a1a1a);cursor:pointer}
.sw-card:hover{border-color:var(--ink-2,#666)}
.sw-card h3{margin:0 0 4px;font-size:15px}
.sw-card.sw-missing{opacity:.6;cursor:default}
.sw-modal{position:absolute;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:10}
.sw-dialog{width:min(520px,92%);max-height:90%;overflow:auto;background:var(--paper,#121212);border:1px solid var(--hairline,#2a2a2a);border-radius:12px;padding:20px}
.sw-field{display:flex;flex-direction:column;gap:4px;margin-bottom:10px}
.sw-field input,.sw-field select,.sw-field textarea{padding:6px 8px;border-radius:6px;border:1px solid var(--hairline,#2a2a2a);background:var(--vellum,#1a1a1a);color:inherit;font:inherit}
.sw-row{display:flex;gap:8px;justify-content:flex-end;margin-top:12px}
.sw-banner{display:flex;gap:8px;align-items:center;padding:8px 12px;background:var(--vellum,#1a1a1a);border-bottom:1px solid var(--hairline,#2a2a2a)}
.sw-toast{position:absolute;right:16px;bottom:16px;padding:10px 14px;border-radius:8px;background:var(--vellum,#1a1a1a);border:1px solid var(--hairline,#2a2a2a);z-index:20;max-width:420px}
.sw-toast.sw-error{border-color:var(--oxblood,#e06c75)}
.sw-menu{position:relative}.sw-menu-list{position:absolute;right:0;top:110%;background:var(--paper,#121212);border:1px solid var(--hairline,#2a2a2a);border-radius:8px;padding:4px;z-index:5;min-width:160px}
.sw-menu-list button{display:block;width:100%;text-align:left;padding:6px 10px;background:none;border:0;color:inherit;font:inherit;cursor:pointer;border-radius:4px}
.sw-menu-list button:hover{background:var(--vellum,#1a1a1a)}
.cm-tooltip-autocomplete{font-family:'Courier Prime','Courier New',monospace}
`;
}
```

`plugins/script-writer/src/ui/useUiSettings.js`:
```js
import { useCallback, useEffect, useState } from 'react';

export const DEFAULT_UI = { sceneNav: true, panel: 'page', dark: false, paper: 'letter', focus: false };

export function useUiSettings(plugin) {
  const [ui, setUi] = useState(DEFAULT_UI);
  useEffect(() => {
    let live = true;
    plugin.settings.get('ui').then((v) => { if (live && v && typeof v === 'object') setUi({ ...DEFAULT_UI, ...v }); }).catch(() => {});
    return () => { live = false; };
  }, [plugin]);
  const patch = useCallback((p) => {
    setUi((cur) => {
      const next = { ...cur, ...p };
      plugin.settings.set('ui', next).catch(() => {});
      return next;
    });
  }, [plugin]);
  return [ui, patch];
}
```

- [ ] **Step 4: Implement `TitlePageFields.jsx` and `NewScriptDialog.jsx`**

`plugins/script-writer/src/ui/TitlePageFields.jsx`:
```jsx
const FIELDS = [
  ['title', 'Title'], ['credit', 'Credit'], ['author', 'Author'],
  ['source', 'Source (optional)'], ['draft_date', 'Draft date'], ['contact', 'Contact'],
];

export function TitlePageFields({ value, onChange }) {
  return FIELDS.map(([key, label]) => (
    <label key={key} className="sw-field">
      <span className="sw-muted">{label}</span>
      {key === 'contact'
        ? <textarea rows={3} value={value[key] ?? ''} onChange={(e) => onChange({ ...value, [key]: e.target.value })} />
        : <input value={value[key] ?? ''} onChange={(e) => onChange({ ...value, [key]: e.target.value })} />}
    </label>
  ));
}
```

`plugins/script-writer/src/ui/NewScriptDialog.jsx`:
```jsx
import { useEffect, useState } from 'react';
import { createProject, listContexts, listProjects, readScript, writeScript } from '../api/backend.js';
import { DEFAULT_META, freeScriptPath, normalizeMeta } from '../fountain/document.js';
import { entryFor, upsertEntry } from '../store/registry.js';
import { TitlePageFields } from './TitlePageFields.jsx';

const NEW = '__new__';
const STARTER = 'FADE IN:\n\nINT. LOCATION - DAY\n\n';

export function NewScriptDialog({ plugin, initial, onCreate, onCancel }) {
  const [meta, setMeta] = useState(() => ({
    ...DEFAULT_META, draft_date: new Date().toISOString().slice(0, 10), ...(initial?.meta ?? {}),
  }));
  const [projects, setProjects] = useState([]);
  const [contexts, setContexts] = useState([]);
  const [projectKey, setProjectKey] = useState(NEW);
  const [newContext, setNewContext] = useState('');
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([listProjects(plugin), listContexts(plugin)]).then(([ps, cs]) => {
      const active = ps.filter((p) => !p.archived);
      setProjects(active);
      setContexts(cs);
      setNewContext(cs[0] ?? '');
      if (active.length) setProjectKey(`${active[0].context}/${active[0].slug}`);
    }).catch((e) => setError(`Could not load projects: ${e.message}`));
  }, [plugin]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      if (!meta.title.trim()) throw new Error('Give the script a title');
      let project = projects.find((p) => `${p.context}/${p.slug}` === projectKey);
      if (projectKey === NEW) {
        if (!newContext || !newName.trim()) throw new Error('Pick a context and name the project');
        project = await createProject(plugin, newContext, newName.trim());
      }
      const path = await freeScriptPath({
        context: project.context, project: project.slug, title: meta.title,
        exists: async (p) => (await readScript(plugin, p)) !== null,
      });
      const full = normalizeMeta({ ...meta, updated: new Date().toISOString() });
      await writeScript(plugin, path, full, initial?.body?.trim() ? initial.body : STARTER);
      await upsertEntry(plugin.settings, entryFor(path, full, 1));
      onCreate(path);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  const byContext = projects.reduce((acc, p) => ({ ...acc, [p.context]: [...(acc[p.context] ?? []), p] }), {});
  return (
    <div className="sw-modal" role="dialog" aria-label="New script">
      <div className="sw-dialog">
        <h2 style={{ marginTop: 0 }}>{initial ? 'Import script' : 'New script'}</h2>
        <label className="sw-field">
          <span className="sw-muted">Project</span>
          <select value={projectKey} onChange={(e) => setProjectKey(e.target.value)}>
            {Object.entries(byContext).map(([ctx, ps]) => (
              <optgroup key={ctx} label={ctx}>
                {ps.map((p) => <option key={p.id} value={`${p.context}/${p.slug}`}>{p.name}</option>)}
              </optgroup>
            ))}
            <option value={NEW}>+ New project…</option>
          </select>
        </label>
        {projectKey === NEW && (
          <div style={{ display: 'flex', gap: 8 }}>
            <label className="sw-field" style={{ flex: 1 }}>
              <span className="sw-muted">Context</span>
              <select value={newContext} onChange={(e) => setNewContext(e.target.value)}>
                {contexts.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label className="sw-field" style={{ flex: 2 }}>
              <span className="sw-muted">Project name</span>
              <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="The Long Night" />
            </label>
          </div>
        )}
        <TitlePageFields value={meta} onChange={setMeta} />
        {error && <div className="sw-status sw-err">{error}</div>}
        <div className="sw-row">
          <button type="button" className="sw-btn" onClick={onCancel} disabled={busy}>Cancel</button>
          <button type="button" className="sw-btn sw-primary" onClick={create} disabled={busy}>{busy ? 'Creating…' : 'Create'}</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Implement `Library.jsx`, `App.jsx`, the placeholder `EditorScreen.jsx`, and `renderer.jsx`**

`plugins/script-writer/src/ui/Library.jsx`:
```jsx
import { Clapperboard, FileUp, Plus, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { fromFountain } from '../fountain/document.js';
import { loadRegistry, removeEntry } from '../store/registry.js';
import { NewScriptDialog } from './NewScriptDialog.jsx';

const when = (iso) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
};

export function Library({ plugin, onOpen, notify }) {
  const [entries, setEntries] = useState(null);
  const [dialog, setDialog] = useState(null); // null | {initial?}

  const reload = useCallback(() => loadRegistry(plugin.settings).then(setEntries).catch((e) => notify(e.message, 'error')), [plugin, notify]);
  useEffect(() => { reload(); }, [reload]);

  async function importFountain() {
    try {
      const r = await plugin.ipc.invoke('import-file');
      if (!r || r.canceled) return;
      const parsed = fromFountain(r.content);
      if (parsed.meta.title === 'Untitled') parsed.meta.title = r.name.replace(/\.[^.]+$/, '');
      setDialog({ initial: parsed });
    } catch (e) {
      notify(`Import failed: ${e.message}`, 'error');
    }
  }

  const sorted = [...(entries ?? [])].sort((a, b) => String(b.updated).localeCompare(String(a.updated)));
  return (
    <div className="sw-lib">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Clapperboard size={20} />
        <h1 style={{ margin: 0, fontSize: 20, flex: 1 }}>Scripts</h1>
        <button type="button" className="sw-btn" onClick={importFountain}><FileUp size={14} />Import .fountain</button>
        <button type="button" className="sw-btn sw-primary" onClick={() => setDialog({})}><Plus size={14} />New script</button>
      </div>
      {entries && sorted.length === 0 && <p className="sw-muted" style={{ marginTop: 24 }}>No scripts yet. Create one or import a .fountain file.</p>}
      <div className="sw-grid">
        {sorted.map((e) => (
          <div key={e.path} className={`sw-card${e.missing ? ' sw-missing' : ''}`}
            onClick={() => !e.missing && onOpen(e.path)} role="button" tabIndex={0}
            onKeyDown={(ev) => ev.key === 'Enter' && !e.missing && onOpen(e.path)}>
            <h3>{e.title}</h3>
            <div className="sw-muted">{e.context} · {e.project}</div>
            <div className="sw-muted">{e.pages ?? 0} pp · {when(e.updated)}</div>
            {e.missing && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                <span className="sw-status sw-err">Missing from vault</span>
                <button type="button" className="sw-btn" onClick={async (ev) => { ev.stopPropagation(); setEntries(await removeEntry(plugin.settings, e.path)); }}>
                  <Trash2 size={14} />Remove
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
      {dialog && (
        <NewScriptDialog plugin={plugin} initial={dialog.initial}
          onCancel={() => setDialog(null)}
          onCreate={(path) => { setDialog(null); onOpen(path); }} />
      )}
    </div>
  );
}
```

`plugins/script-writer/src/ui/App.jsx`:
```jsx
import { useCallback, useRef, useState } from 'react';
import { EditorScreen } from './EditorScreen.jsx';
import { Library } from './Library.jsx';

export function App({ plugin }) {
  const [route, setRoute] = useState({ name: 'library' });
  const [toast, setToast] = useState(null);
  const timer = useRef(null);
  const notify = useCallback((msg, kind = 'info') => {
    clearTimeout(timer.current);
    setToast({ msg, kind });
    timer.current = setTimeout(() => setToast(null), 6000);
  }, []);
  return (
    <div className="sw-root">
      {route.name === 'library'
        ? <Library plugin={plugin} notify={notify} onOpen={(path) => setRoute({ name: 'editor', path })} />
        : <EditorScreen key={route.path} plugin={plugin} path={route.path} notify={notify} onBack={() => setRoute({ name: 'library' })} />}
      {toast && <div className={`sw-toast${toast.kind === 'error' ? ' sw-error' : ''}`} role="status">{toast.msg}</div>}
    </div>
  );
}
```

`plugins/script-writer/src/ui/EditorScreen.jsx` (placeholder; Task 12 replaces it):
```jsx
export function EditorScreen({ path, onBack }) {
  return (
    <div className="sw-lib">
      <button type="button" className="sw-btn" onClick={onBack}>Back</button>
      <p className="sw-muted">{path}</p>
    </div>
  );
}
```

`plugins/script-writer/src/renderer.jsx`:
```jsx
import { createRoot } from 'react-dom/client';
import { App } from './ui/App.jsx';
import { appCss } from './ui/styles.js';

export function mount(el, plugin) {
  for (const [k, v] of Object.entries(plugin.theme ?? {})) if (v) el.style.setProperty(k, v);
  const style = document.createElement('style');
  style.textContent = appCss();
  const host = document.createElement('div');
  host.style.height = '100%';
  el.append(style, host);
  const root = createRoot(host);
  root.render(<App plugin={plugin} />);
  return () => {
    root.unmount();
    el.replaceChildren();
  };
}
```

- [ ] **Step 6: Run the tests**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run
```
Expected: PASS for the whole suite. The smoke test may log a React `act()` warning, which is acceptable. If `lucide-react` 1.x doesn't export `Clapperboard`, `FileUp`, `Plus` or `Trash2`, find the right names with `grep -o "Clapperboard\|FileUp\|Trash2" node_modules/lucide-react/dist/esm/lucide-react.js | sort -u` and adjust the imports.

- [ ] **Step 7: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer/src && git commit -m "feat(script-writer): UI shell — library, new-script/import dialog, styles

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Editor screen (CodeMirror view, navigators, page view, save, export)

**Files:**
- Create: `plugins/script-writer/src/editor/decorations.js`, `autocaps.js`, `focus.js`, `keymap.js`, `setup.js`
- Create: `plugins/script-writer/src/ui/SceneNav.jsx`, `CharacterList.jsx`, `PageView.jsx`
- Modify: `plugins/script-writer/src/ui/EditorScreen.jsx` (replace the placeholder)
- Test: `plugins/script-writer/src/editor/__tests__/setup.test.js` (jsdom smoke)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `createEditor({parent, doc, onDocChange(text), onCursorLine(line0), onSave(), onToggleFocus()}) → EditorView`.
  - `setFocusMode(view, on)`.
  - `jumpToLine(view, line0)`.

- [ ] **Step 1: Write the failing jsdom smoke test for the editor wiring**

`plugins/script-writer/src/editor/__tests__/setup.test.js`:
```js
// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { createEditor, jumpToLine, setFocusMode } from '../setup.js';

describe('createEditor', () => {
  it('decorates lines by element type and reports changes', () => {
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    const changes = [];
    const view = createEditor({ parent, doc: 'INT. HOUSE - DAY\n\nMARA\nHi.', onDocChange: (t) => changes.push(t) });
    const classes = [...parent.querySelectorAll('.cm-line')].map((l) => l.className);
    expect(classes[0]).toContain('sw-l-scene_heading');
    expect(classes[2]).toContain('sw-l-character');
    expect(classes[3]).toContain('sw-l-dialogue');
    view.dispatch({ changes: { from: view.state.doc.length, insert: '!' } });
    expect(changes.at(-1)).toBe('INT. HOUSE - DAY\n\nMARA\nHi.!');
    jumpToLine(view, 2);
    expect(view.state.doc.lineAt(view.state.selection.main.head).number).toBe(3);
    setFocusMode(view, true);
    expect(parent.querySelectorAll('.sw-dim').length).toBeGreaterThan(0);
    view.destroy();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/editor/__tests__/setup.test.js
```
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the editor extensions**

`plugins/script-writer/src/editor/decorations.js`:
```js
import { RangeSetBuilder } from '@codemirror/state';
import { Decoration, ViewPlugin } from '@codemirror/view';
import { typeAt } from './commands.js';
import { markerRanges } from './flow.js';

const lineDeco = new Map();
const lineClass = (type) => {
  if (!lineDeco.has(type)) lineDeco.set(type, Decoration.line({ class: `sw-l-${type}` }));
  return lineDeco.get(type);
};
const markDeco = { 'sw-marker': Decoration.mark({ class: 'sw-marker' }), 'sw-note': Decoration.mark({ class: 'sw-note' }) };

function build(view) {
  const b = new RangeSetBuilder();
  const { state } = view;
  for (const { from, to } of view.visibleRanges) {
    for (let pos = from; pos <= to;) {
      const line = state.doc.lineAt(pos);
      const type = typeAt(state, line.number);
      if (type) {
        b.add(line.from, line.from, lineClass(type));
        for (const [s, e, cls] of markerRanges(line.text, type)) if (e > s) b.add(line.from + s, line.from + e, markDeco[cls]);
      }
      pos = line.to + 1;
    }
  }
  return b.finish();
}

export const decorations = ViewPlugin.fromClass(class {
  constructor(view) { this.decorations = build(view); }
  update(u) {
    if (u.docChanged || u.viewportChanged || u.selectionSet || u.transactions.some((t) => t.effects.length)) {
      this.decorations = build(u.view);
    }
  }
}, { decorations: (v) => v.decorations });
```

`plugins/script-writer/src/editor/autocaps.js`:
```js
import { EditorView } from '@codemirror/view';
import { typeAt } from './commands.js';
import { CAPS_TYPES } from './flow.js';

/** Scene headings, cues and transitions are always uppercase in a screenplay. */
export const autoCaps = EditorView.inputHandler.of((view, from, to, text) => {
  if (text === text.toUpperCase()) return false;
  const line = view.state.doc.lineAt(from);
  if (!CAPS_TYPES.has(typeAt(view.state, line.number))) return false;
  view.dispatch({ changes: { from, to, insert: text.toUpperCase() }, selection: { anchor: from + text.length }, userEvent: 'input.type' });
  return true;
});
```

`plugins/script-writer/src/editor/focus.js`:
```js
import { EditorState, RangeSetBuilder } from '@codemirror/state';
import { Decoration, EditorView, ViewPlugin } from '@codemirror/view';

const dim = Decoration.line({ class: 'sw-dim' });

function paragraph(doc, n) {
  let a = n;
  let b = n;
  while (a > 1 && doc.line(a - 1).text.trim() !== '') a--;
  while (b < doc.lines && doc.line(b + 1).text.trim() !== '') b++;
  return [a, b];
}

function build(view) {
  const { doc } = view.state;
  const [a, b] = paragraph(doc, doc.lineAt(view.state.selection.main.head).number);
  const out = new RangeSetBuilder();
  for (const { from, to } of view.visibleRanges) {
    for (let pos = from; pos <= to;) {
      const line = doc.lineAt(pos);
      if (line.number < a || line.number > b) out.add(line.from, line.from, dim);
      pos = line.to + 1;
    }
  }
  return out.finish();
}

const dimmer = ViewPlugin.fromClass(class {
  constructor(v) { this.decorations = build(v); }
  update(u) { if (u.docChanged || u.selectionSet || u.viewportChanged) this.decorations = build(u.view); }
}, { decorations: (v) => v.decorations });

/** Typewriter scrolling: keep the caret vertically centred. */
const typewriter = EditorState.transactionExtender.of((tr) => (
  tr.selection || tr.docChanged ? { effects: EditorView.scrollIntoView(tr.newSelection.main.head, { y: 'center' }) } : null
));

export const focusMode = [dimmer, typewriter];
```

`plugins/script-writer/src/editor/keymap.js`:
```js
import { insertNewline } from '@codemirror/commands';
import { Prec } from '@codemirror/state';
import { keymap } from '@codemirror/view';
import { cycleType, enter, setType } from './commands.js';

const BY_NUMBER = ['scene_heading', 'action', 'character', 'parenthetical', 'dialogue', 'transition', 'centered'];

export function scriptKeymap({ onSave, onToggleFocus } = {}) {
  return Prec.high(keymap.of([
    { key: 'Tab', run: cycleType(1), preventDefault: true },
    { key: 'Shift-Tab', run: cycleType(-1), preventDefault: true },
    { key: 'Enter', run: enter },
    { key: 'Shift-Enter', run: insertNewline },
    { key: 'Mod-s', run: () => { onSave?.(); return true; }, preventDefault: true },
    { key: 'Mod-Shift-f', run: () => { onToggleFocus?.(); return true; }, preventDefault: true },
    ...BY_NUMBER.map((t, i) => ({ key: `Mod-${i + 1}`, run: setType(t), preventDefault: true })),
  ]));
}
```

`plugins/script-writer/src/editor/setup.js`:
```js
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { Compartment, EditorState } from '@codemirror/state';
import { drawSelection, EditorView, keymap } from '@codemirror/view';
import { analysisField } from './analysis.js';
import { autoCaps } from './autocaps.js';
import { scriptCompletions } from './complete.js';
import { decorations } from './decorations.js';
import { focusMode } from './focus.js';
import { hintField } from './hints.js';
import { scriptKeymap } from './keymap.js';

const focusSlot = new Compartment();

export function createEditor({ parent, doc, onDocChange, onCursorLine, onSave, onToggleFocus }) {
  const state = EditorState.create({
    doc,
    extensions: [
      analysisField,
      hintField,
      history(),
      drawSelection(),
      EditorView.lineWrapping,
      scriptKeymap({ onSave, onToggleFocus }),
      keymap.of([...historyKeymap, ...defaultKeymap]),
      decorations,
      scriptCompletions(),
      autoCaps,
      focusSlot.of([]),
      EditorView.contentAttributes.of({ spellcheck: 'true', 'aria-label': 'Screenplay' }),
      EditorView.domEventHandlers({ blur: () => { onSave?.(); return false; } }),
      EditorView.updateListener.of((u) => {
        if (u.docChanged) onDocChange?.(u.state.doc.toString());
        if (u.docChanged || u.selectionSet) onCursorLine?.(u.state.doc.lineAt(u.state.selection.main.head).number - 1);
      }),
    ],
  });
  return new EditorView({ state, parent });
}

export function setFocusMode(view, on) {
  view.dispatch({ effects: focusSlot.reconfigure(on ? focusMode : []) });
}

export function jumpToLine(view, line0) {
  const n = Math.min(Math.max(line0 + 1, 1), view.state.doc.lines);
  const pos = view.state.doc.line(n).from;
  view.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: 'start', yMargin: 96 }) });
  view.focus();
}
```

- [ ] **Step 4: Run the smoke test**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run src/editor
```
Expected: PASS. In jsdom, CodeMirror may render only the visible range. With a 4-line doc every line renders. If `view.visibleRanges` comes back empty under jsdom (height 0), `build()` produces no decorations. In that case add `parent.style.height = '800px'` before `createEditor` in the test. Don't change production code for it.

- [ ] **Step 5: Implement the side panels and page view**

`plugins/script-writer/src/ui/SceneNav.jsx`:
```jsx
import { useState } from 'react';

export function SceneNav({ scenes, cursorLine, onJump, onMove }) {
  const [drag, setDrag] = useState(null);
  const [over, setOver] = useState(null);
  const active = scenes.reduce((cur, s) => (s.line <= cursorLine ? s.index : cur), -1);
  return (
    <div>
      <div className="sw-h">Scenes · {scenes.length}</div>
      {scenes.map((s) => (
        <div key={`${s.line}-${s.heading}`} draggable
          className={`sw-scene${s.index === active ? ' sw-active' : ''}${over === s.index && drag !== null ? ' sw-over' : ''}`}
          onClick={() => onJump(s.line)}
          onDragStart={() => setDrag(s.index)}
          onDragOver={(e) => { e.preventDefault(); setOver(s.index); }}
          onDragLeave={() => setOver(null)}
          onDrop={(e) => { e.preventDefault(); if (drag !== null && drag !== s.index) onMove(drag, s.index); setDrag(null); setOver(null); }}
          onDragEnd={() => { setDrag(null); setOver(null); }}>
          <span className="sw-num">{s.number}</span>{s.heading}
          {s.synopsis && <div className="sw-syn">{s.synopsis}</div>}
        </div>
      ))}
    </div>
  );
}
```

`plugins/script-writer/src/ui/CharacterList.jsx`:
```jsx
import { useRef } from 'react';

export function CharacterList({ characters, onJump }) {
  const next = useRef(new Map());
  return (
    <div>
      <div className="sw-h">Characters · {characters.length}</div>
      {characters.map((c) => (
        <div key={c.name} className="sw-char" title="Click to cycle through their speeches"
          onClick={() => {
            const k = (next.current.get(c.name) ?? 0) % c.lines.length;
            next.current.set(c.name, k + 1);
            onJump(c.lines[k]);
          }}>
          <span>{c.name}</span><span className="sw-muted">{c.count}</span>
        </div>
      ))}
    </div>
  );
}
```

`plugins/script-writer/src/ui/PageView.jsx`:
```jsx
import { useMemo } from 'react';
import { pageCss, renderPage, renderTitlePage } from '../render/pageHtml.js';

export function PageView({ meta, pages, paper }) {
  const html = useMemo(() => renderTitlePage(meta) + pages.map(renderPage).join(''), [meta, pages]);
  return (
    <div className="sw-pagewrap">
      <style>{pageCss(paper)}</style>
      <div style={{ zoom: 0.5 }} dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}
```

- [ ] **Step 6: Implement `EditorScreen.jsx` (replacing the placeholder)**

`plugins/script-writer/src/ui/EditorScreen.jsx`:
```jsx
import { ArrowLeft, Download, Eye, FileText, Focus, Hash, ListTree, Moon } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { readScript, writeScript } from '../api/backend.js';
import { draftKey, parseScriptPath, toFountain } from '../fountain/document.js';
import { characters as listCharacters, moveScene, scenes as listScenes } from '../fountain/outline.js';
import { parse } from '../fountain/parse.js';
import { createEditor, jumpToLine, setFocusMode } from '../editor/setup.js';
import { paginate } from '../paginate/paginate.js';
import { documentHtml, FONT_PLACEHOLDER } from '../render/pageHtml.js';
import { entryFor, markMissing, upsertEntry } from '../store/registry.js';
import { createSaver, shouldOfferDraft } from '../store/saver.js';
import { CharacterList } from './CharacterList.jsx';
import { PageView } from './PageView.jsx';
import { SceneNav } from './SceneNav.jsx';
import { TitlePageFields } from './TitlePageFields.jsx';
import { useUiSettings } from './useUiSettings.js';

const STATUS_TEXT = { saved: 'Saved', dirty: 'Unsaved', saving: 'Saving…' };

export function EditorScreen({ plugin, path, onBack, notify }) {
  const [loaded, setLoaded] = useState(null); // {meta, body}
  const [meta, setMeta] = useState(null);
  const [ui, patchUi] = useUiSettings(plugin);
  const [status, setStatus] = useState({ s: 'saved' });
  const [elements, setElements] = useState([]);
  const [cursorLine, setCursorLine] = useState(0);
  const [draft, setDraft] = useState(null);
  const [titleEdit, setTitleEdit] = useState(null);
  const [menu, setMenu] = useState(false);
  const hostRef = useRef(null);
  const viewRef = useRef(null);
  const metaRef = useRef(null);
  const saverRef = useRef(null);
  const analyzeTimer = useRef(null);
  const key = draftKey(path);
  const slug = parseScriptPath(path)?.slug ?? 'screenplay';

  // Load the script (and any newer unsaved draft).
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const s = await readScript(plugin, path);
        if (!live) return;
        if (!s) {
          await markMissing(plugin.settings, path);
          notify('That script is no longer in the vault — marked missing.', 'error');
          onBack();
          return;
        }
        metaRef.current = s.meta;
        setMeta(s.meta);
        setLoaded(s);
        const d = await plugin.ipc.invoke('draft-read', key).catch(() => null);
        if (live && shouldOfferDraft(d, s.meta, s.body)) setDraft(d);
      } catch (e) {
        notify(`Could not open script: ${e.message}`, 'error');
        onBack();
      }
    })();
    return () => { live = false; };
  }, [plugin, path]); // eslint-disable-line react-hooks/exhaustive-deps

  const analyzeSoon = useCallback((text) => {
    clearTimeout(analyzeTimer.current);
    analyzeTimer.current = setTimeout(() => setElements(parse(text)), 400);
  }, []);

  // Saver: one per opened script.
  useEffect(() => {
    if (!loaded) return undefined;
    const saver = createSaver({
      save: async (body) => {
        const next = { ...metaRef.current, updated: new Date().toISOString() };
        await writeScript(plugin, path, next, body);
        metaRef.current = next;
        const pages = paginate(parse(body), { sceneNumbers: next.scene_numbers }).length;
        await upsertEntry(plugin.settings, entryFor(path, next, pages));
        await plugin.ipc.invoke('draft-clear', key).catch(() => {});
      },
      mirror: (body) => plugin.ipc.invoke('draft-write', { key, content: body, savedAt: new Date().toISOString() }),
      onStatus: (s, info) => setStatus({ s, info }),
    });
    saverRef.current = saver;
    const onWindowBlur = () => saver.flush();
    window.addEventListener('blur', onWindowBlur);
    return () => {
      window.removeEventListener('blur', onWindowBlur);
      saver.flush().finally(() => saver.dispose());
    };
  }, [loaded, plugin, path, key]);

  // CodeMirror view.
  useEffect(() => {
    if (!loaded || !hostRef.current) return undefined;
    const view = createEditor({
      parent: hostRef.current,
      doc: loaded.body,
      onDocChange: (text) => { saverRef.current?.change(text); analyzeSoon(text); },
      onCursorLine: setCursorLine,
      onSave: () => saverRef.current?.flush(),
      onToggleFocus: () => patchUi({ focus: !viewRef.current?.swFocus }),
    });
    viewRef.current = view;
    setElements(parse(loaded.body));
    view.focus();
    return () => { clearTimeout(analyzeTimer.current); view.destroy(); viewRef.current = null; };
  }, [loaded, analyzeSoon, patchUi]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.swFocus = ui.focus;
    setFocusMode(view, ui.focus);
  }, [ui.focus, loaded]);

  const pages = useMemo(() => paginate(elements, { sceneNumbers: meta?.scene_numbers }), [elements, meta?.scene_numbers]);
  const sceneList = useMemo(() => listScenes(elements), [elements]);
  const charList = useMemo(() => listCharacters(elements), [elements]);

  const jump = (line0) => viewRef.current && jumpToLine(viewRef.current, line0);
  const touch = () => viewRef.current && saverRef.current?.change(viewRef.current.state.doc.toString());
  const updateMeta = (patch) => {
    const next = { ...metaRef.current, ...patch };
    metaRef.current = next;
    setMeta(next);
    touch();
  };

  function onMoveScene(from, to) {
    const view = viewRef.current;
    const text = view.state.doc.toString();
    const next = moveScene(text, from, to);
    if (next !== text) view.dispatch({ changes: { from: 0, to: text.length, insert: next }, userEvent: 'move.scene' });
  }

  function restoreDraft() {
    const view = viewRef.current;
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: draft.content } });
    setDraft(null);
    notify('Unsaved draft restored.');
  }

  async function exportPdf() {
    setMenu(false);
    try {
      await saverRef.current?.flush();
      const body = viewRef.current.state.doc.toString();
      const html = documentHtml({ meta: metaRef.current, pages: paginate(parse(body), { sceneNumbers: metaRef.current.scene_numbers }), paper: ui.paper, fontBase: FONT_PLACEHOLDER });
      const r = await plugin.ipc.invoke('export-pdf', { html, defaultName: slug, paper: ui.paper });
      if (r?.path) notify(`PDF saved to ${r.path}`);
    } catch (e) {
      notify(`PDF export failed: ${e.message}`, 'error');
    }
  }

  async function exportFountain() {
    setMenu(false);
    try {
      const content = toFountain(metaRef.current, viewRef.current.state.doc.toString());
      const r = await plugin.ipc.invoke('export-file', { defaultName: slug, ext: 'fountain', content });
      if (r?.path) notify(`Fountain saved to ${r.path}`);
    } catch (e) {
      notify(`Export failed: ${e.message}`, 'error');
    }
  }

  if (!loaded || !meta) return <div className="sw-lib sw-muted">Opening…</div>;
  const statusLabel = status.s === 'error'
    ? `Unsaved — retrying in ${Math.round((status.info?.retryInMs ?? 0) / 1000)}s`
    : STATUS_TEXT[status.s];

  return (
    <>
      <div className="sw-bar">
        <button type="button" className="sw-btn" onClick={onBack} title="Library"><ArrowLeft size={14} /></button>
        <span className="sw-title" onClick={() => setTitleEdit(meta)} title="Edit title page">{meta.title}</span>
        <span className="sw-grow" />
        <span className="sw-muted">{pages.length} pp · ~{pages.length} min</span>
        <span className={`sw-status${status.s === 'error' ? ' sw-err' : ''}`} title={status.info?.message ?? ''}>{statusLabel}</span>
        <button type="button" className={`sw-btn${ui.sceneNav ? ' sw-on' : ''}`} onClick={() => patchUi({ sceneNav: !ui.sceneNav })} title="Scenes & characters"><ListTree size={14} /></button>
        <button type="button" className={`sw-btn${ui.panel === 'page' ? ' sw-on' : ''}`} onClick={() => patchUi({ panel: ui.panel === 'page' ? null : 'page' })} title="Page view"><Eye size={14} /></button>
        <button type="button" className={`sw-btn${meta.scene_numbers ? ' sw-on' : ''}`} onClick={() => updateMeta({ scene_numbers: !meta.scene_numbers })} title="Scene numbers"><Hash size={14} /></button>
        <button type="button" className={`sw-btn${ui.focus ? ' sw-on' : ''}`} onClick={() => patchUi({ focus: !ui.focus })} title="Focus mode (⌘⇧F)"><Focus size={14} /></button>
        <button type="button" className={`sw-btn${ui.dark ? ' sw-on' : ''}`} onClick={() => patchUi({ dark: !ui.dark })} title="Dark page"><Moon size={14} /></button>
        <select className="sw-btn" value={ui.paper} onChange={(e) => patchUi({ paper: e.target.value })} title="Paper size">
          <option value="letter">US Letter</option>
          <option value="a4">A4</option>
        </select>
        <div className="sw-menu">
          <button type="button" className="sw-btn" onClick={() => setMenu(!menu)}><Download size={14} />Export</button>
          {menu && (
            <div className="sw-menu-list">
              <button type="button" onClick={exportPdf}>PDF</button>
              <button type="button" onClick={exportFountain}><FileText size={12} /> Fountain</button>
            </div>
          )}
        </div>
      </div>
      {draft && (
        <div className="sw-banner">
          <span>An unsaved draft from {new Date(draft.savedAt).toLocaleString()} was found.</span>
          <span className="sw-grow" />
          <button type="button" className="sw-btn sw-primary" onClick={restoreDraft}>Restore</button>
          <button type="button" className="sw-btn" onClick={() => { plugin.ipc.invoke('draft-clear', key).catch(() => {}); setDraft(null); }}>Discard</button>
        </div>
      )}
      <div className="sw-body">
        {ui.sceneNav && (
          <aside className="sw-side">
            <SceneNav scenes={sceneList} cursorLine={cursorLine} onJump={jump} onMove={onMoveScene} />
            <CharacterList characters={charList} onJump={jump} />
          </aside>
        )}
        <main className={`sw-main${ui.dark ? ' sw-dark' : ''}`}>
          <div className="sw-sheet" ref={hostRef} />
        </main>
        {ui.panel === 'page' && (
          <aside className="sw-right"><PageView meta={meta} pages={pages} paper={ui.paper} /></aside>
        )}
      </div>
      {titleEdit && (
        <div className="sw-modal" role="dialog" aria-label="Title page">
          <div className="sw-dialog">
            <h2 style={{ marginTop: 0 }}>Title page</h2>
            <TitlePageFields value={titleEdit} onChange={setTitleEdit} />
            <div className="sw-row">
              <button type="button" className="sw-btn" onClick={() => setTitleEdit(null)}>Cancel</button>
              <button type="button" className="sw-btn sw-primary" onClick={() => { updateMeta(titleEdit); setTitleEdit(null); }}>Save</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
```

- [ ] **Step 7: Run the full suite and build**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run && npm run build && ls -la dist
```
Expected: all tests PASS, and the build succeeds with `main.cjs`, `renderer.mjs` and `fonts/`. If lucide lacks any icon name, fix the import as in Task 11 Step 6.

- [ ] **Step 8: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer/src && git commit -m "feat(script-writer): editor screen — live page, navigators, page view, autosave, export

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Ship the build, README, and manual verification in the app

**Files:**
- Create: `plugins/script-writer/README.md`
- Commit: `plugins/script-writer/dist/**`

**Interfaces:**
- Consumes: the whole plugin.
- Produces: an installable plugin folder, verified in the running app.

- [ ] **Step 1: Write the README**

`plugins/script-writer/README.md`:
```markdown
# Script Writer

A screenplay editor for Poltergeist. Write in plain [Fountain](https://fountain.io) while the page formats itself as you type, then export an industry-standard PDF.

## Writing

| Key | Does |
|---|---|
| Tab / Shift-Tab | Cycle the current line: Action → Character → (Parenthetical) → Transition → Scene heading |
| Enter | Next logical element: heading → action, character → dialogue, dialogue → character, transition → heading. Enter on an empty line returns to action. |
| Shift-Enter | New line within the same element |
| ⌘1–⌘7 | Scene heading, Action, Character, Parenthetical, Dialogue, Transition, Centered |
| ⌘S | Save now (autosaves 1.5 s after you stop typing) |
| ⌘⇧F | Focus mode (dims everything but the current paragraph; typewriter scrolling) |

Autocomplete offers `INT./EXT.` prefixes, known locations, `DAY/NIGHT/…`, character names, and `(V.O.)/(O.S.)/(CONT'D)`.

## Where scripts live

Each script is a vault note in its project folder:
`20-contexts/<context>/projects/<project>/<title>.screenplay.md`. Frontmatter holds the title page and the body is Fountain, so scripts are searchable like any note. Put your research, bios and outlines in the same project folder.

If the backend is unreachable, saving retries automatically and your text is mirrored locally. The next time you open the script you'll be offered the unsaved draft.

## Output

Courier Prime 12pt, 1.5" / 1" margins, 54 lines per page. Pagination handles `(MORE)` / `(CONT'D)`, never ends a page on a scene heading, and has optional scene numbers. US Letter or A4. Export PDF or `.fountain`, and import `.fountain`.

Courier Prime is © Quote-Unquote Apps, SIL Open Font License (see `dist/fonts/OFL.txt`).

## Develop

    npm install && npm test && npm run build   # commit dist/
```

- [ ] **Step 2: Rebuild, run everything, and commit `dist/`**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer/plugins/script-writer && npx vitest run && npm run build && cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer && git branch --show-current && git add plugins/script-writer/README.md plugins/script-writer/dist plugins/script-writer/package-lock.json && git status --short plugins/script-writer && git commit -m "feat(script-writer): README + committed dist build

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
Expected: the tests pass and `git status` shows `dist/main.cjs`, `dist/renderer.mjs` and `dist/fonts/*` staged, with no `node_modules`.

- [ ] **Step 3: Install and verify in the running app (manual; record the results)**

In Poltergeist, go to **Plugins → Install from folder** and pick `…/.claude/worktrees/script-writer/plugins/script-writer`. Then work through this checklist and record pass or fail for each item:

1. **Loads.** The plugin shows as `enabled` and a "Script Writer" sidebar entry with the clapperboard icon appears. Not `errored` or `invalid`.
2. **New script.**
   - Create one in a new project; check it appears in the Plugins data dir registry, and that `20-contexts/<ctx>/projects/<slug>/<title>.screenplay.md` exists in the vault with frontmatter.
   - Create a second script with the same title and confirm it becomes `<title>-2`.
3. **Keyboard-only scene.** Type a scene using only the keyboard:
   - `int. lighthouse - night` then Enter → uppercased heading, cursor on an action line after a blank.
   - `Rain.` Enter, then Tab → the line becomes a character cue. Type `mara` → it appears as `MARA`. Enter → the dialogue indent.
   - Type a line, then Enter → a character line. Enter again → back to action.
   - Tab on an empty line under a cue → `()` with the cursor inside.
4. **Autocomplete.** `i` offers `INT.`, and a repeat location and character name are suggested.
5. **Page view.**
   - Matches the editor. Add about 60 lines of dialogue for one character and see `(MORE)` / `MARA (CONT'D)` across pages.
   - Page numbers appear from page 2.
   - The scene-number toggle shows numbers in both margins.
6. **Navigators.**
   - Clicking a scene jumps to it, and dragging a scene reorders the text. ⌘Z undoes the reorder in one step.
   - Clicking a character cycles through their speeches.
7. **Autosave.**
   - The status goes Unsaved → Saving… → Saved, and the vault file updates.
   - Stop the sidecar (or quit the backend), type, and see "Unsaved — retrying in Ns" with the text kept. Reopen the script and the "Restore" banner appears. Restart the backend and the status returns to Saved.
8. **Export PDF.**
   - Open the PDF. It should have Courier Prime, a title page, 1.5" left margin, 54 lines per page, and the page numbers from the page view.
   - Compare against the same `.fountain` exported to Highland or Final Draft if available: page count within ±1.
9. **Export and import Fountain.** Export `.fountain`, import it back through the Library, and confirm the new script has the same title-page fields and body.
10. **Focus mode and dark page.** ⌘⇧F dims non-current paragraphs and keeps the caret centred. Dark mode keeps the text readable.

Fix any failures with a test first where the logic is pure (Tasks 2–9 modules), rebuild, reinstall (**Plugins → reload**), and re-check. Commit each fix separately.

- [ ] **Step 4: Finish the branch**

Use superpowers:finishing-a-development-branch to push `feat/script-writer` and open the PR. The PR description lists the manual checklist results from Step 3.
