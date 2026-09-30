# Script Writer — Slice 2 (AI co-writer, Polish, formatting UX, FDX) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the AI features to the shipped Script Writer plugin (v0.1.0 → v0.2.0):
- An **Ask panel** that answers from the vault, with citations.
- **Inline AI actions** shown as an accept/reject diff.
- **Polish**, which reviews the whole document per scene.
- A **formatting toolbar** (element dropdown, B/I/U) and **+ Scene**.
- **FDX** import and export.

**Architecture:**
- **Pure modules** under `src/ai/`, `src/diff/` and `src/fdx/` do retrieval, prompts, validation, diffs, the polish engine and FDX conversion. They are tested in node or jsdom with fake sidecars.
- **Editor-side pieces** are CodeMirror extensions: `src/editor/proposal.js` (an inline suggestion widget), `src/editor/format.js` and `src/editor/context.js`.
- **React components** (`AiPanel`, `FormatBar`, `PolishDialog`, `PolishReview`) are wired into `EditorScreen`.
- **All AI calls** go through `POST /v1/llm/run`, which uses the user's configured provider, via `plugin.sidecar.request`.

**Tech Stack:** Plain ESM JS + JSX, React 18, CodeMirror 6, `marked` (new dependency), vitest (+ jsdom), esbuild.

**Spec:** `docs/superpowers/specs/2026-09-30-script-writer-plugin-design.md`. §5 is binding: Scope, Retrieval, Ask, Actions, Polish, and Formatting toolbar and new scenes. The §6 FDX bullets are binding too.

## Global Constraints

- **Paths.** The plugin lives at `plugins/script-writer/`. Work in the worktree `/Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer-ai`, branch `feat/script-writer-ai`. Every Bash command starts with `cd <absolute path> &&`, and you check `git branch --show-current` before committing.
- **Backend calls.** Renderer backend calls go ONLY through `call(plugin, method, path, body)` in `src/api/backend.js`. That wraps `plugin.sidecar.request` and throws an Error with `.status`. There is no `plugin.api.fetch` in the renderer.
- **LLM calls.** Every LLM call uses `runLlm()` from `src/ai/llm.js`:
  - `POST /v1/llm/run {prompt, system?, jsonSchema?, budgetUsd, timeoutSeconds: 240}`. Omit `model`.
  - `budgetUsd` is always explicit: Ask **1.00**, actions **1.00**, Polish **0.50 per section**.
  - The response is `{text, structured, error, costUsd}`. A non-null `error` is thrown.
- **Search.** `POST /v1/search {q (1..500 chars), limit: 50}` returns `{items: [{path, title, snippet, score}]}`. `GET /v1/notes?path=<encoded>` returns `{path, title, body, frontmatter}`, or 404.
- **Scope prefixes.**
  - Project: `20-contexts/<ctx>/projects/<project>/`
  - Context: `20-contexts/<ctx>/`
  - Vault: `''`
  - The script's own path is never a source.
- **Polish passes.** Formatting and language are on by default; tighten and dialogue are off.
- **Polish execution.** Concurrency is **3**. A polished section is rejected (and the original kept) if it is empty, has no screenplay elements, keeps fewer than **60%** of the original's non-blank lines (when the original has at least 5), or drops the scene heading.
- **AI edits never apply silently.**
  - An action proposal is cancelled if its target text is edited.
  - Polish Apply is refused if the doc changed since Polish started.
  - Every accept or apply is one transaction, so it is one ⌘Z.
- **ASCII-only source.**
  - Use `…` / `—` escapes in JS strings.
  - JSX attribute strings do NOT process escapes. Write `placeholder={'Ask…'}`, never `placeholder="Ask…"`.
  - In JSX text use `&hellip;` / `&mdash;` / `&middot;`.
  - Check with `grep -rnP '[^\x00-\x7F]' src | grep -v '//'` before each commit.
- **Commits.** Messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Never stage `plugins/script-writer/dist/` or `node_modules` before Task 11.
- **CSS.** Styles go in `src/ui/styles.js` `appCss()`. Append each task's CSS at the END of the template literal, and use `var(--x, fallback)` theme tokens.

## Review Focus

1. **Garbage LLM output** (fenced code, empty text, prose instead of Fountain, a truncated scene) must be rejected or shown as text, never applied as an edit. Tests: Task 2 (`checkFountain`), Task 8 (polish rejection), Task 7 (the action shows invalid output as a message).
2. **An AI edit landing on text the user changed meanwhile.** Tests: Task 4 (the proposal cancels on an overlapping edit and maps through edits elsewhere), Task 9 (apply is refused when the doc changed).
3. **Provider errors, timeouts or budget exhaustion** mid-polish. One section failing must not sink the others, and the error must be visible. Test: Task 8 (a mixed success/error/rejected run).
4. **Citations `[n]`** must point to the right source. The script itself must never be a source, and the project→context widening must happen only below 3 hits. Tests: Task 1 and Task 7.
5. **Partial polish acceptance** must compose exactly: every hunk off equals the original, and every hunk on equals the polished text. Test: Task 8 (`composePolished`).

---

## File Structure

```
plugins/script-writer/src/
  ai/llm.js            runLlm, BUDGETS, LLM_TIMEOUT_S
  ai/retrieve.js       SCOPES, scopePrefix, retrieve
  ai/prompts.js        FOUNTAIN_RULES, outlineText, askPrompt, ACTIONS, REWRITE_PRESETS, actionPrompt,
                       POLISH_PASSES, polishPrompt, EDIT_SCHEMA, POLISH_SCHEMA
  ai/validate.js       stripFences, checkFountain
  ai/polish.js         polishUnits, polishDocument, composePolished, POLISH_CONCURRENCY
  diff/lineDiff.js     diffLines, hunks, applyHunks, wordDiff
  editor/proposal.js   proposalField, showProposal, clearProposal, accept/insert/rejectProposal, proposalExtension
  editor/context.js    editorContext(state)
  editor/format.js     MARKERS, toggleEmphasis, insertSceneAfterCursor
  fdx/export.js        toFdx
  fdx/import.js        fromFdx
  fountain/outline.js  + sceneBlocks, joinBlocks, sceneRange, sceneInsertPos (moveScene refactored onto them)
  main/threads.js      readThread, writeThread, clearThread
  main.js              + thread-read|write|clear handlers
  main/files.js        + 'fdx' in IMPORT_EXTS/EXPORT_EXTS
  ui/FormatBar.jsx  ui/AiPanel.jsx  ui/PolishDialog.jsx  ui/PolishReview.jsx
  ui/EditorScreen.jsx  ui/SceneNav.jsx  ui/Library.jsx  ui/styles.js  editor/setup.js  editor/keymap.js   (modified)
```

---

### Task 1: LLM client and vault retrieval

**Files:**
- Create: `src/ai/llm.js`, `src/ai/retrieve.js`
- Test: `src/ai/__tests__/llm.test.js`, `src/ai/__tests__/retrieve.test.js`

**Interfaces:**
- Consumes: `call(plugin, method, path, body)` from `src/api/backend.js`, and `parseScriptPath(path) → {context, project, slug} | null` from `src/fountain/document.js`.
- Produces:
  - `BUDGETS = {ask: 1, action: 1, polishPerSection: 0.5}` and `LLM_TIMEOUT_S = 240`.
  - `runLlm(plugin, {prompt, system?, jsonSchema?, budgetUsd, timeoutSeconds?}) → {text, structured, costUsd}`.
  - `SCOPES = ['project', 'context', 'vault']` and `scopePrefix(scriptPath, scope) → string`.
  - `retrieve(plugin, {query, scriptPath, scope}) → {sources: Source[], scopeUsed, widened}`, where `Source = {n, path, title, snippet, score, content?}`.

- [ ] **Step 1: Write the failing tests**

`src/ai/__tests__/llm.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { BUDGETS, runLlm } from '../llm.js';

function fake(reply) {
  const calls = [];
  return {
    calls,
    sidecar: { request: async (method, path, body) => { calls.push({ method, path, body }); return reply(body); } },
  };
}

describe('runLlm', () => {
  it('posts prompt, system, schema, explicit budget and timeout (no model)', async () => {
    const p = fake(() => ({ ok: true, data: { text: 'hi', structured: { fountain: 'X' }, error: null, costUsd: 0.01 } }));
    const out = await runLlm(p, { prompt: 'P', system: 'S', jsonSchema: { type: 'object' }, budgetUsd: BUDGETS.ask });
    expect(p.calls[0]).toEqual({ method: 'POST', path: '/v1/llm/run', body: { prompt: 'P', system: 'S', jsonSchema: { type: 'object' }, budgetUsd: 1, timeoutSeconds: 240 } });
    expect(out).toEqual({ text: 'hi', structured: { fountain: 'X' }, costUsd: 0.01 });
  });
  it('refuses to run without an explicit budget', async () => {
    await expect(runLlm(fake(() => ({ ok: true, data: {} })), { prompt: 'P' })).rejects.toThrow(/budgetUsd/);
  });
  it('throws the provider error and HTTP errors', async () => {
    await expect(runLlm(fake(() => ({ ok: true, data: { text: '', error: 'RateLimit: slow down' } })), { prompt: 'P', budgetUsd: 1 }))
      .rejects.toThrow('RateLimit: slow down');
    await expect(runLlm(fake(() => ({ ok: false, error: 'sidecar down', status: 502 })), { prompt: 'P', budgetUsd: 1 }))
      .rejects.toThrow('sidecar down');
  });
  it('requires a structured result when a schema was requested', async () => {
    await expect(runLlm(fake(() => ({ ok: true, data: { text: 'prose', structured: null, error: null } })), { prompt: 'P', jsonSchema: {}, budgetUsd: 1 }))
      .rejects.toThrow(/structured/);
  });
});
```

`src/ai/__tests__/retrieve.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { retrieve, scopePrefix } from '../retrieve.js';

const SCRIPT = '20-contexts/personal/projects/night/draft.screenplay.md';
const hit = (path, k) => ({ path, title: `T${k}`, snippet: `S${k}`, score: 1 - k / 100 });

function fake(items, notes = {}) {
  const calls = [];
  return {
    calls,
    sidecar: {
      request: async (method, path, body) => {
        calls.push({ method, path, body });
        if (method === 'POST' && path === '/v1/search') return { ok: true, data: { query: body.q, total: items.length, items } };
        if (method === 'GET' && path.startsWith('/v1/notes?path=')) {
          const p = decodeURIComponent(path.slice('/v1/notes?path='.length));
          if (notes[p] instanceof Error) return { ok: false, error: notes[p].message, status: 500 };
          return notes[p] !== undefined ? { ok: true, data: { path: p, body: notes[p] } } : { ok: false, error: 'nf', status: 404 };
        }
        return { ok: false, error: 'no route', status: 500 };
      },
    },
  };
}

describe('scopePrefix', () => {
  it('maps scopes to vault prefixes', () => {
    expect(scopePrefix(SCRIPT, 'project')).toBe('20-contexts/personal/projects/night/');
    expect(scopePrefix(SCRIPT, 'context')).toBe('20-contexts/personal/');
    expect(scopePrefix(SCRIPT, 'vault')).toBe('');
    expect(scopePrefix('odd/path.md', 'project')).toBe('');
  });
});

describe('retrieve', () => {
  it('filters to the project, drops the script itself, numbers from 1 and fetches top-4 bodies truncated', async () => {
    const items = [
      hit(SCRIPT, 0),
      ...Array.from({ length: 6 }, (_, k) => hit(`20-contexts/personal/projects/night/n${k}.md`, k + 1)),
      hit('20-contexts/personal/other.md', 9),
    ];
    const notes = Object.fromEntries(items.map((h) => [h.path, 'x'.repeat(5000)]));
    const p = fake(items, notes);
    const r = await retrieve(p, { query: 'Who is Mara?', scriptPath: SCRIPT, scope: 'project' });
    expect(p.calls[0]).toEqual({ method: 'POST', path: '/v1/search', body: { q: 'Who is Mara?', limit: 50 } });
    expect(r.widened).toBe(false);
    expect(r.sources.map((s) => s.n)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(r.sources.every((s) => s.path.includes('/projects/night/n'))).toBe(true);
    expect(r.sources.slice(0, 4).every((s) => s.content.length === 4000)).toBe(true);
    expect(r.sources[4].content).toBeUndefined();
  });
  it('widens project to context below 3 hits and says so', async () => {
    const items = [hit('20-contexts/personal/projects/night/a.md', 1), hit('20-contexts/personal/b.md', 2), hit('20-contexts/personal/c.md', 3)];
    const r = await retrieve(fake(items), { query: 'q', scriptPath: SCRIPT, scope: 'project' });
    expect(r).toMatchObject({ widened: true, scopeUsed: 'context' });
    expect(r.sources).toHaveLength(3);
  });
  it('keeps at most 8 sources, tolerates a failing note fetch, skips empty queries', async () => {
    const items = Array.from({ length: 12 }, (_, k) => hit(`20-contexts/work/n${k}.md`, k));
    const notes = { '20-contexts/work/n0.md': new Error('boom'), '20-contexts/work/n1.md': 'body' };
    const r = await retrieve(fake(items, notes), { query: 'q', scriptPath: SCRIPT, scope: 'vault' });
    expect(r.sources).toHaveLength(8);
    expect(r.sources[0].content).toBeUndefined();
    expect(r.sources[1].content).toBe('body');
    const p = fake(items);
    expect(await retrieve(p, { query: '   ', scriptPath: SCRIPT })).toEqual({ sources: [], scopeUsed: 'project', widened: false });
    expect(p.calls).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run to verify failure**

`cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer-ai/plugins/script-writer && npx vitest run src/ai`. Expected: FAIL, modules not found.

- [ ] **Step 3: Implement**

`src/ai/llm.js`:
```js
// Single door to the user's configured AI provider (POST /v1/llm/run).
import { call } from '../api/backend.js';

export const BUDGETS = Object.freeze({ ask: 1, action: 1, polishPerSection: 0.5 });
export const LLM_TIMEOUT_S = 240; // the renderer's sidecar bridge gives up at 300s

export async function runLlm(plugin, { prompt, system, jsonSchema, budgetUsd, timeoutSeconds = LLM_TIMEOUT_S }) {
  if (!(typeof budgetUsd === 'number' && budgetUsd > 0)) throw new Error('runLlm: an explicit budgetUsd is required');
  const body = { prompt };
  if (system) body.system = system;
  if (jsonSchema) body.jsonSchema = jsonSchema;
  body.budgetUsd = budgetUsd;
  body.timeoutSeconds = timeoutSeconds;
  const data = await call(plugin, 'POST', '/v1/llm/run', body);
  if (data?.error) throw new Error(data.error);
  if (jsonSchema && (data?.structured === null || data?.structured === undefined)) {
    throw new Error('The AI returned no structured result');
  }
  return { text: data?.text ?? '', structured: data?.structured ?? null, costUsd: data?.costUsd ?? null };
}
```

`src/ai/retrieve.js`:
```js
// Vault retrieval for the co-writer: semantic search, scoped by path prefix.
import { call } from '../api/backend.js';
import { parseScriptPath } from '../fountain/document.js';

export const SCOPES = ['project', 'context', 'vault'];
const MAX_SOURCES = 8;
const FULL_SOURCES = 4;
const FULL_CHARS = 4000;
const WIDEN_BELOW = 3;

export function scopePrefix(scriptPath, scope) {
  const p = parseScriptPath(scriptPath);
  if (!p || scope === 'vault') return '';
  if (scope === 'context') return `20-contexts/${p.context}/`;
  return `20-contexts/${p.context}/projects/${p.project}/`;
}

export async function retrieve(plugin, { query, scriptPath, scope = 'project' }) {
  const q = String(query ?? '').trim().slice(0, 500);
  if (!q) return { sources: [], scopeUsed: scope, widened: false };
  const res = await call(plugin, 'POST', '/v1/search', { q, limit: 50 });
  const items = (res?.items ?? []).filter((h) => h && h.path !== scriptPath);
  const pick = (s) => items.filter((h) => h.path.startsWith(scopePrefix(scriptPath, s))).slice(0, MAX_SOURCES);
  let scopeUsed = scope;
  let hits = pick(scope);
  let widened = false;
  if (scope === 'project' && hits.length < WIDEN_BELOW) {
    hits = pick('context');
    scopeUsed = 'context';
    widened = true;
  }
  const sources = await Promise.all(hits.map(async (h, k) => {
    const src = { n: k + 1, path: h.path, title: h.title, snippet: h.snippet, score: h.score };
    if (k < FULL_SOURCES) {
      try {
        const note = await call(plugin, 'GET', `/v1/notes?path=${encodeURIComponent(h.path)}`);
        src.content = String(note?.body ?? '').slice(0, FULL_CHARS);
      } catch {
        // snippet only: one unreadable note must not fail the question
      }
    }
    return src;
  }));
  return { sources, scopeUsed, widened };
}
```

- [ ] **Step 4: Run tests.** Run `npx vitest run src/ai`. Expected: PASS.
- [ ] **Step 5: Commit** `src/ai` as "feat(script-writer): LLM client + scoped vault retrieval".

---

### Task 2: Scene helpers, prompts, output validation

**Files:**
- Modify: `src/fountain/outline.js` (add `sceneBlocks`, `joinBlocks`, `sceneRange`, `sceneInsertPos`; refactor `moveScene` onto `sceneBlocks`/`joinBlocks`)
- Create: `src/ai/prompts.js`, `src/ai/validate.js`
- Test: `src/fountain/__tests__/outline.test.js` (append), `src/ai/__tests__/prompts.test.js`, `src/ai/__tests__/validate.test.js`

**Interfaces:**
- Produces from `outline.js`:
  - `sceneBlocks(text) → {pre, blocks: [{line, text}], trailingNewline}` and `joinBlocks(sb) → string`.
  - `sceneRange(text, line0) → {startLine, endLine}`, with 0-based inclusive lines and trailing blank lines trimmed.
  - `sceneInsertPos(text, line0) → offset`, the end of the scene containing `line0`.
- Produces from `prompts.js`: `FOUNTAIN_RULES`, `outlineText(elements)`, `sourcesText(sources)`, and `askPrompt({question, outline, scene, sources, history}) → {system, prompt}`.
  - `ACTIONS: [{id, label, edits: 'insert'|'replace'|'none', needsDirection?, instruction}]`, plus `REWRITE_PRESETS`.
  - `actionPrompt({action, direction, target, outline, sources}) → {system, prompt, jsonSchema?}`.
  - `POLISH_PASSES: [{id, label, default, rule}]`, and `polishPrompt({passes, sceneText, characterNames}) → {system, prompt, jsonSchema}`.
  - `EDIT_SCHEMA` and `POLISH_SCHEMA`.
- Produces from `validate.js`: `stripFences(s)`, and `checkFountain(original, result, {minKeep = 0.6, keepHeading = false}) → {ok, text, reason?}`.

- [ ] **Step 1: Write failing tests**

Append to `src/fountain/__tests__/outline.test.js`, and add `sceneBlocks, joinBlocks, sceneRange, sceneInsertPos` to its import from `'../outline.js'`:
```js
describe('scene blocks', () => {
  const T = 'FADE IN:\n\nINT. A - DAY\n\nHi.\n\n\nINT. B - DAY\n\nYo.\n';
  it('splits preamble and scenes, trimming trailing blank lines', () => {
    expect(sceneBlocks(T)).toEqual({ pre: 'FADE IN:', blocks: [{ line: 2, text: 'INT. A - DAY\n\nHi.' }, { line: 7, text: 'INT. B - DAY\n\nYo.' }], trailingNewline: true });
  });
  it('joins with one blank line and round-trips normalised text', () => {
    expect(joinBlocks(sceneBlocks(T))).toBe('FADE IN:\n\nINT. A - DAY\n\nHi.\n\nINT. B - DAY\n\nYo.\n');
    const norm = joinBlocks(sceneBlocks(T));
    expect(joinBlocks(sceneBlocks(norm))).toBe(norm);
  });
  it('handles no headings and no preamble', () => {
    expect(sceneBlocks('Just action.')).toEqual({ pre: 'Just action.', blocks: [], trailingNewline: false });
    expect(joinBlocks(sceneBlocks('INT. A - DAY\n\nGo.'))).toBe('INT. A - DAY\n\nGo.');
  });
  it('finds the scene range around a line and the insert position after it', () => {
    expect(sceneRange(T, 4)).toEqual({ startLine: 2, endLine: 4 });
    expect(sceneRange(T, 0)).toEqual({ startLine: 0, endLine: 0 });
    expect(sceneRange(T, 9)).toEqual({ startLine: 7, endLine: 9 });
    expect(sceneInsertPos(T, 4)).toBe('FADE IN:\n\nINT. A - DAY\n\nHi.'.length);
  });
});
```

`src/ai/__tests__/validate.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { checkFountain, stripFences } from '../validate.js';

const SCENE = 'INT. A - DAY\n\nMara waits.\n\nMARA\nNow?\n\nJOE\nNot yet.\n\nShe sits.';

describe('validate', () => {
  it('strips code fences and CRLF', () => {
    expect(stripFences('```fountain\r\nINT. A - DAY\r\n```')).toBe('INT. A - DAY');
  });
  it('accepts sound Fountain', () => {
    expect(checkFountain(SCENE, SCENE.replace('waits', 'paces'))).toEqual({ ok: true, text: SCENE.replace('waits', 'paces') });
  });
  it('rejects empty, element-less, over-shortened and heading-less results', () => {
    expect(checkFountain(SCENE, '   ')).toMatchObject({ ok: false, reason: 'empty result' });
    expect(checkFountain(SCENE, '[[just a note]]')).toMatchObject({ ok: false, reason: 'no screenplay elements' });
    expect(checkFountain(SCENE, 'INT. A - DAY\n\nMara waits.')).toMatchObject({ ok: false });
    expect(checkFountain(SCENE, 'Mara waits.\n\nMARA\nNow?\n\nJOE\nNot yet.\n\nShe sits.', { keepHeading: true })).toMatchObject({ ok: false, reason: 'scene heading removed' });
  });
  it('allows shortening when minKeep is 0', () => {
    expect(checkFountain(SCENE, 'INT. A - DAY\n\nMara waits.', { minKeep: 0 }).ok).toBe(true);
  });
});
```

`src/ai/__tests__/prompts.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { parse } from '../../fountain/parse.js';
import { ACTIONS, POLISH_PASSES, actionPrompt, askPrompt, outlineText, polishPrompt } from '../prompts.js';

const els = parse('INT. A - DAY\n\n= She arrives.\n\nGo.\n\nEXT. B - NIGHT\n\nRun.');
const sources = [{ n: 1, path: 'p/a.md', title: 'Mara bio', snippet: 's', content: 'Mara is 40.' }, { n: 2, path: 'p/b.md', title: 'Town', snippet: 'Foggy.' }];

describe('prompts', () => {
  it('outlines scenes with synopses', () => {
    expect(outlineText(els)).toBe('1. INT. A - DAY — She arrives.\n2. EXT. B - NIGHT');
  });
  it('builds an ask prompt with numbered sources, scene, last 6 turns and the question', () => {
    const history = Array.from({ length: 8 }, (_, k) => ({ role: k % 2 ? 'assistant' : 'user', text: `t${k}` }));
    const { system, prompt } = askPrompt({ question: 'How old is Mara?', outline: 'O', scene: 'SCENE', sources, history });
    expect(system).toMatch(/\[n\]/);
    expect(prompt).toContain('[1] Mara bio (p/a.md)\nMara is 40.');
    expect(prompt).toContain('[2] Town (p/b.md)\nFoggy.');
    expect(prompt).toContain('SCENE');
    expect(prompt).not.toContain('t1');
    expect(prompt).toContain('t7');
    expect(prompt.trim().endsWith('How old is Mara?')).toBe(true);
  });
  it('says so when there are no sources', () => {
    expect(askPrompt({ question: 'q', outline: '', scene: '', sources: [], history: [] }).prompt).toContain('(no matching notes found)');
  });
  it('builds action prompts with a schema only for editing actions', () => {
    const rewrite = ACTIONS.find((a) => a.id === 'rewrite');
    const r = actionPrompt({ action: rewrite, direction: 'darker', target: 'TARGET', outline: 'O', sources });
    expect(r.jsonSchema.required).toEqual(['fountain']);
    expect(r.prompt).toContain("Writer's direction: darker");
    expect(r.prompt.trim().endsWith('TARGET')).toBe(true);
    const cont = actionPrompt({ action: ACTIONS.find((a) => a.id === 'continuity'), target: 'T', outline: '', sources });
    expect(cont.jsonSchema).toBeUndefined();
    expect(ACTIONS.map((a) => a.id)).toEqual(['continue', 'rewrite', 'punchup', 'beat', 'continuity']);
  });
  it('builds a polish prompt listing only the chosen passes', () => {
    expect(POLISH_PASSES.filter((p) => p.default).map((p) => p.id)).toEqual(['formatting', 'language']);
    const { prompt, jsonSchema } = polishPrompt({ passes: ['formatting'], sceneText: 'SECTION', characterNames: ['MARA'] });
    expect(prompt).toContain(POLISH_PASSES[0].rule);
    expect(prompt).not.toContain(POLISH_PASSES[1].rule);
    expect(prompt).toContain('MARA');
    expect(jsonSchema.required).toEqual(['fountain']);
  });
});
```

- [ ] **Step 2: Run to verify failure**

`npx vitest run src/ai src/fountain`. Expected: the new tests FAIL.

- [ ] **Step 3: Implement**

In `src/fountain/outline.js`, keep `scenes`, `cueName`, `characters` and `trimBlankTail` unchanged, and replace `moveScene` with:
```js
export function sceneBlocks(text) {
  const heads = parse(text).filter((e) => e.type === 'scene_heading').map((e) => e.line);
  const lines = text.split('\n');
  const first = heads.length ? heads[0] : lines.length;
  return {
    pre: trimBlankTail(lines.slice(0, first)).join('\n'),
    blocks: heads.map((h, k) => ({ line: h, text: trimBlankTail(lines.slice(h, heads[k + 1] ?? lines.length)).join('\n') })),
    trailingNewline: text.endsWith('\n'),
  };
}

export function joinBlocks({ pre, blocks, trailingNewline }) {
  const parts = [pre, ...blocks.map((b) => b.text)].filter((p) => p.trim() !== '');
  return parts.join('\n\n') + (trailingNewline ? '\n' : '');
}

export function moveScene(text, from, to) {
  const sb = sceneBlocks(text);
  const n = sb.blocks.length;
  if (from === to || from < 0 || to < 0 || from >= n || to >= n) return text;
  const blocks = [...sb.blocks];
  const [moved] = blocks.splice(from, 1);
  blocks.splice(to, 0, moved);
  return joinBlocks({ ...sb, blocks });
}

export function sceneRange(text, line0) {
  const lines = text.split('\n');
  const heads = parse(text).filter((e) => e.type === 'scene_heading').map((e) => e.line);
  let start = 0;
  for (const h of heads) if (h <= line0) start = h;
  const next = heads.find((h) => h > line0);
  let end = (next ?? lines.length) - 1;
  while (end > start && lines[end].trim() === '') end--;
  return { startLine: start, endLine: Math.max(start, end) };
}

export function sceneInsertPos(text, line0) {
  const { endLine } = sceneRange(text, line0);
  return text.split('\n').slice(0, endLine + 1).join('\n').length;
}
```

`src/ai/validate.js`:
```js
import { parse } from '../fountain/parse.js';

const PRINTED = new Set(['scene_heading', 'action', 'character', 'dialogue', 'parenthetical', 'transition', 'centered', 'lyric']);
const nonBlank = (s) => s.split('\n').filter((l) => l.trim()).length;

export function stripFences(s) {
  return String(s ?? '').replace(/\r\n?/g, '\n').replace(/^\s*```[a-z]*\n?/i, '').replace(/\n?```\s*$/, '').trim();
}

export function checkFountain(original, result, { minKeep = 0.6, keepHeading = false } = {}) {
  const text = stripFences(result);
  if (!text) return { ok: false, reason: 'empty result', text };
  const els = parse(text);
  if (!els.some((e) => PRINTED.has(e.type))) return { ok: false, reason: 'no screenplay elements', text };
  const a = nonBlank(original);
  const b = nonBlank(text);
  if (minKeep > 0 && a >= 5 && b < a * minKeep) {
    return { ok: false, reason: `lost ${Math.round(100 - (100 * b) / a)}% of its lines`, text };
  }
  if (keepHeading && parse(original).some((e) => e.type === 'scene_heading') && !els.some((e) => e.type === 'scene_heading')) {
    return { ok: false, reason: 'scene heading removed', text };
  }
  return { ok: true, text };
}
```

`src/ai/prompts.js`:
```js
// Prompt builders. Pure: every input is passed in; nothing reads app state.
import { scenes } from '../fountain/outline.js';

const SYSTEM_BASE = 'You are an experienced screenwriting collaborator working on a feature screenplay written in Fountain markup.';

export const FOUNTAIN_RULES = [
  'Write valid Fountain: scene headings start with INT. or EXT. and are uppercase;',
  'character cues are uppercase on their own line with dialogue directly beneath;',
  'parentheticals are in (brackets) on their own line; one blank line between elements;',
  'no markdown, no code fences, no commentary inside the screenplay text.',
].join(' ');

export function outlineText(elements) {
  return scenes(elements).slice(0, 200)
    .map((s) => `${s.number}. ${s.heading}${s.synopsis ? ` — ${s.synopsis}` : ''}`).join('\n');
}

export function sourcesText(sources) {
  return sources.map((s) => `[${s.n}] ${s.title} (${s.path})\n${s.content ?? s.snippet ?? ''}`).join('\n\n---\n\n');
}

export function askPrompt({ question, outline, scene, sources, history = [] }) {
  const system = `${SYSTEM_BASE} Answer the writer's question using the numbered notes from their vault. `
    + 'Cite notes inline as [n]. If the notes do not cover the question, say so plainly, then offer your own suggestion. '
    + 'Answer in concise markdown.';
  const turns = history.slice(-6).map((t) => `${t.role === 'user' ? 'Writer' : 'You'}: ${t.text}`).join('\n\n');
  const prompt = [
    `## Script outline\n${outline || '(no scenes yet)'}`,
    `## Current scene\n${scene || '(none)'}`,
    `## Notes from the vault\n${sources.length ? sourcesText(sources) : '(no matching notes found)'}`,
    turns ? `## Conversation so far\n${turns}` : '',
    `## Question\n${question}`,
  ].filter(Boolean).join('\n\n');
  return { system, prompt };
}

export const EDIT_SCHEMA = Object.freeze({
  type: 'object',
  properties: { fountain: { type: 'string' }, notes: { type: 'string' } },
  required: ['fountain'],
});

export const REWRITE_PRESETS = ['Tighter', 'Funnier', 'Darker', 'More subtext'];

export const ACTIONS = [
  { id: 'continue', label: 'Continue scene', edits: 'insert', instruction: 'Continue the scene from where the target text ends. Write only the next beats (roughly 5 to 25 lines of Fountain). Do not repeat the target text.' },
  { id: 'rewrite', label: 'Rewrite…', edits: 'replace', needsDirection: true, instruction: "Rewrite the target text following the writer's direction. Keep the story events and characters unless the direction says otherwise." },
  { id: 'punchup', label: 'Punch up dialogue', edits: 'replace', instruction: 'Sharpen only the dialogue in the target text: voice, rhythm, subtext. Keep scene headings, action lines and character cues exactly as they are.' },
  { id: 'beat', label: 'Scene from beat', edits: 'replace', instruction: 'The target text is a beat or synopsis. Write it as a complete scene in Fountain, starting with a scene heading.' },
  { id: 'continuity', label: 'Continuity check', edits: 'none', instruction: 'Check the target text against the notes for contradictions: names, ages, relationships, timeline, locations and established facts. List each issue with a citation [n] and a suggested fix. If there are none, say so.' },
];

export function actionPrompt({ action, direction = '', target, outline, sources }) {
  const system = action.edits === 'none'
    ? `${SYSTEM_BASE} Cite notes inline as [n]. Answer in concise markdown.`
    : `${SYSTEM_BASE} ${FOUNTAIN_RULES} Put the screenplay text in "fountain" and any brief remarks for the writer in "notes".`;
  const prompt = [
    `## Script outline\n${outline || '(no scenes yet)'}`,
    `## Notes from the vault\n${sources.length ? sourcesText(sources) : '(no matching notes found)'}`,
    `## Task\n${action.instruction}${direction ? `\nWriter's direction: ${direction}` : ''}`,
    `## Target text\n${target}`,
  ].join('\n\n');
  return action.edits === 'none' ? { system, prompt } : { system, prompt, jsonSchema: EDIT_SCHEMA };
}

export const POLISH_SCHEMA = Object.freeze({
  type: 'object',
  properties: { fountain: { type: 'string' }, changes: { type: 'string' } },
  required: ['fountain'],
});

export const POLISH_PASSES = [
  { id: 'formatting', label: 'Formatting', default: true, rule: "Fix Fountain formatting so it is industry-correct: uppercase scene headings and character cues, exactly one blank line between elements, dialogue directly under its cue, parentheticals in brackets on their own line, consistent character names and extensions such as (V.O.), (O.S.) and (CONT'D). Do not change any words." },
  { id: 'language', label: 'Language', default: true, rule: "Fix spelling, grammar and punctuation in action and dialogue. Keep the writer's voice, slang and intentional fragments." },
  { id: 'tighten', label: 'Tighten prose', default: false, rule: 'Tighten action lines: cut filler and redundant description and prefer active verbs, keeping every story beat. Do not change dialogue.' },
  { id: 'dialogue', label: 'Punch up dialogue', default: false, rule: 'Punch up dialogue: sharper voice, rhythm and subtext for each character, keeping what happens in the scene.' },
];

export function polishPrompt({ passes, sceneText, characterNames = [] }) {
  const rules = POLISH_PASSES.filter((p) => passes.includes(p.id)).map((p, i) => `${i + 1}. ${p.rule}`).join('\n');
  const system = `${SYSTEM_BASE} ${FOUNTAIN_RULES} You are polishing one section of a longer script. `
    + 'Return the whole section, polished, in "fountain", and a one-line summary of what you changed in "changes".';
  const prompt = [
    `## Passes\n${rules}\nApply ONLY these passes. Everything they do not cover must stay exactly as written.`,
    `## Known characters\n${characterNames.join(', ') || '(none)'}`,
    `## Section\n${sceneText}`,
  ].join('\n\n');
  return { system, prompt, jsonSchema: POLISH_SCHEMA };
}
```

- [ ] **Step 4: Run tests.** Run `npx vitest run`. Expected: all PASS, including the existing moveScene tests, unchanged.
- [ ] **Step 5: Commit** as "feat(script-writer): scene blocks, AI prompts and output validation".

---

### Task 3: Line and word diff

**Files:**
- Create: `src/diff/lineDiff.js`
- Test: `src/diff/__tests__/lineDiff.test.js`

**Interfaces:**
- Produces:
  - `diffLines(a: string[], b: string[]) → [{type: 'equal'|'del'|'add', text}]`.
  - `hunks(a, b) → [{type: 'equal', lines} | {type: 'change', del: string[], add: string[]}]`.
  - `applyHunks(hunks, accept: (changeIndex) => boolean) → string[]`.
  - `wordDiff(x: string, y: string) → [{type, text}]`.

- [ ] **Step 1: Write failing tests**

`src/diff/__tests__/lineDiff.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { applyHunks, diffLines, hunks, wordDiff } from '../lineDiff.js';

const A = ['INT. A - DAY', '', 'Mara wait.', '', 'MARA', 'Now?'];
const B = ['INT. A - DAY', '', 'Mara waits.', '', 'MARA', 'Now?', '', 'She sits.'];

describe('lineDiff', () => {
  it('diffs lines with LCS', () => {
    expect(diffLines(['a', 'b', 'c'], ['a', 'x', 'c'])).toEqual([
      { type: 'equal', text: 'a' }, { type: 'del', text: 'b' }, { type: 'add', text: 'x' }, { type: 'equal', text: 'c' },
    ]);
  });
  it('groups into hunks and re-applies all/none/partial exactly', () => {
    const hs = hunks(A, B);
    expect(hs.filter((h) => h.type === 'change')).toEqual([
      { type: 'change', del: ['Mara wait.'], add: ['Mara waits.'] },
      { type: 'change', del: [], add: ['', 'She sits.'] },
    ]);
    expect(applyHunks(hs, () => true)).toEqual(B);
    expect(applyHunks(hs, () => false)).toEqual(A);
    expect(applyHunks(hs, (i) => i === 0)).toEqual(['INT. A - DAY', '', 'Mara waits.', '', 'MARA', 'Now?']);
  });
  it('handles empty sides', () => {
    expect(hunks([], ['x'])).toEqual([{ type: 'change', del: [], add: ['x'] }]);
    expect(hunks(['x'], [])).toEqual([{ type: 'change', del: ['x'], add: [] }]);
    expect(hunks([], [])).toEqual([]);
  });
  it('word-diffs a single edited line, merging runs', () => {
    expect(wordDiff('Mara wait here.', 'Mara waits here.')).toEqual([
      { type: 'equal', text: 'Mara ' }, { type: 'del', text: 'wait' }, { type: 'add', text: 'waits' }, { type: 'equal', text: ' here.' },
    ]);
  });
  it('falls back to a full replace for huge inputs', () => {
    const big = Array.from({ length: 2100 }, (_, k) => `l${k}`);
    const ops = diffLines(big, [...big].reverse());
    expect(ops.filter((o) => o.type === 'equal')).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run to verify failure.** Run `npx vitest run src/diff`. Expected: FAIL.

- [ ] **Step 3: Implement**

`src/diff/lineDiff.js`:
```js
// LCS diffs for reviewing AI edits. Scenes are small; the cap keeps a
// pathological input from allocating a huge table.
const MAX_CELLS = 4_000_000;

function lcsOps(a, b) {
  const n = a.length;
  const m = b.length;
  if (n * m > MAX_CELLS) return [...a.map((t) => ({ type: 'del', text: t })), ...b.map((t) => ({ type: 'add', text: t }))];
  const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  }
  const ops = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { ops.push({ type: 'equal', text: a[i] }); i++; j++; } else if (dp[i + 1][j] >= dp[i][j + 1]) ops.push({ type: 'del', text: a[i++] });
    else ops.push({ type: 'add', text: b[j++] });
  }
  while (i < n) ops.push({ type: 'del', text: a[i++] });
  while (j < m) ops.push({ type: 'add', text: b[j++] });
  return ops;
}

export const diffLines = (a, b) => lcsOps(a, b);

export function hunks(a, b) {
  const out = [];
  for (const op of lcsOps(a, b)) {
    const last = out[out.length - 1];
    if (op.type === 'equal') {
      if (last?.type === 'equal') last.lines.push(op.text); else out.push({ type: 'equal', lines: [op.text] });
    } else {
      if (last?.type !== 'change') out.push({ type: 'change', del: [], add: [] });
      out[out.length - 1][op.type].push(op.text);
    }
  }
  return out;
}

export function applyHunks(hs, accept) {
  const lines = [];
  let c = 0;
  for (const h of hs) {
    if (h.type === 'equal') lines.push(...h.lines);
    else lines.push(...(accept(c++) ? h.add : h.del));
  }
  return lines;
}

export function wordDiff(x, y) {
  const tok = (s) => s.split(/(\s+)/).filter((t) => t !== '');
  const merged = [];
  for (const op of lcsOps(tok(x), tok(y))) {
    const last = merged[merged.length - 1];
    if (last?.type === op.type) last.text += op.text; else merged.push({ ...op });
  }
  return merged;
}
```

- [ ] **Step 4: Run tests.** Expected: PASS. If the huge-input test is slow, it's because the cap isn't being hit: 2100 × 2100 = 4.41M cells, which is over 4M. Check the comparison.
- [ ] **Step 5: Commit** as "feat(script-writer): line/word diff for reviewing AI edits".

---

### Task 4: Inline AI proposal widget and editor context

**Files:**
- Create: `src/editor/proposal.js`, `src/editor/context.js`
- Modify: `src/editor/setup.js`, which adds `proposalExtension` to the extensions and exports `proposeEdit(view, p)`; `src/ui/styles.js`, which gets the CSS
- Test: `src/editor/__tests__/proposal.test.js` (jsdom)

**Interfaces:**
- Consumes: `sceneRange` (Task 2) and `analysisField` (existing).
- Produces:
  - `showProposal`, `clearProposal`, `proposalField`, `proposalExtension`.
  - `acceptProposal(view)`, `insertProposal(view)`, `rejectProposal(view)`, each returning a boolean.
  - `Proposal = {from, to, text, mode: 'replace'|'insert', label}`.
  - `editorContext(state) → {text, elements, cursorLine, scene: {from, to, text}, selection: {from, to, text}}`.
  - From `setup.js`: `proposeEdit(view, proposal)`.

- [ ] **Step 1: Write failing tests**

`src/editor/__tests__/proposal.test.js`:
```js
// @vitest-environment jsdom
import { EditorSelection, EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { describe, expect, it } from 'vitest';
import { analysisField } from '../analysis.js';
import { editorContext } from '../context.js';
import { acceptProposal, insertProposal, proposalExtension, proposalField, rejectProposal, showProposal } from '../proposal.js';

const DOC = 'INT. A - DAY\n\nMara waits.\n\nINT. B - DAY\n\nGo.';
const mk = (doc = DOC, sel = EditorSelection.cursor(16)) => EditorState.create({ doc, selection: sel, extensions: [analysisField, proposalExtension] });
const viewOf = (state) => {
  const v = { state, dispatch: (tr) => { v.state = tr.state; } };
  return v;
};
const P = { from: 14, to: 25, text: 'Mara paces.', mode: 'replace', label: 'Rewrite' };

describe('proposal field', () => {
  it('shows, maps through edits elsewhere, and cancels on overlapping edits', () => {
    let s = mk().update({ effects: showProposal.of(P) }).state;
    expect(s.field(proposalField)).toEqual(P);
    s = s.update({ changes: { from: 0, insert: 'FADE IN:\n\n' } }).state;
    expect(s.field(proposalField)).toMatchObject({ from: 24, to: 35 });
    s = s.update({ changes: { from: 26, insert: 'x' } }).state;
    expect(s.field(proposalField)).toBeNull();
  });
  it('accepts as one change, inserts below, or rejects', () => {
    const v = viewOf(mk().update({ effects: showProposal.of(P) }).state);
    expect(acceptProposal(v)).toBe(true);
    expect(v.state.doc.toString()).toBe(DOC.replace('Mara waits.', 'Mara paces.'));
    expect(v.state.field(proposalField)).toBeNull();

    const w = viewOf(mk().update({ effects: showProposal.of({ ...P, mode: 'insert', from: 25, to: 25, text: 'She sits.' }) }).state);
    expect(insertProposal(w)).toBe(true);
    expect(w.state.doc.toString()).toBe(DOC.replace('Mara waits.', 'Mara waits.\n\nShe sits.'));

    const r = viewOf(mk().update({ effects: showProposal.of(P) }).state);
    expect(rejectProposal(r)).toBe(true);
    expect(r.state.doc.toString()).toBe(DOC);
    expect(acceptProposal(r)).toBe(false);
  });
  it('renders a widget whose Accept button applies the edit', () => {
    const parent = document.createElement('div');
    parent.style.height = '600px';
    document.body.appendChild(parent);
    const view = new EditorView({ state: mk(), parent });
    view.dispatch({ effects: showProposal.of(P) });
    expect(parent.querySelector('.sw-del')?.textContent).toBe('Mara waits.');
    expect(parent.querySelector('.sw-proposal-text')?.textContent).toBe('Mara paces.');
    const accept = [...parent.querySelectorAll('.sw-proposal button')].find((b) => b.textContent === 'Accept');
    accept.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    expect(view.state.doc.toString()).toContain('Mara paces.');
    view.destroy();
  });
});

describe('editorContext', () => {
  it('reports the scene around the cursor and the selection', () => {
    const ctx = editorContext(mk(DOC, EditorSelection.range(14, 18)));
    expect(ctx.scene).toEqual({ from: 0, to: 25, text: 'INT. A - DAY\n\nMara waits.' });
    expect(ctx.selection).toEqual({ from: 14, to: 18, text: 'Mara' });
    expect(ctx.cursorLine).toBe(2);
    expect(ctx.elements.length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run to verify failure.** Run `npx vitest run src/editor/__tests__/proposal.test.js`. Expected: FAIL.

- [ ] **Step 3: Implement**

`src/editor/proposal.js`:
```js
// An AI suggestion shown inline: the target range struck through and the
// proposed Fountain in a block widget with Accept / Insert / Reject.
// Editing inside (or at the edges of) the target cancels the proposal.
import { StateEffect, StateField } from '@codemirror/state';
import { Decoration, EditorView, keymap, WidgetType } from '@codemirror/view';

export const showProposal = StateEffect.define();
export const clearProposal = StateEffect.define();

export const proposalField = StateField.define({
  create: () => null,
  update(p, tr) {
    for (const e of tr.effects) {
      if (e.is(clearProposal)) return null;
      if (e.is(showProposal)) return { ...e.value };
    }
    if (!p || !tr.docChanged) return p;
    let touched = false;
    tr.changes.iterChangedRanges((fromA, toA) => { if (fromA <= p.to && toA >= p.from) touched = true; });
    if (touched) return null;
    return { ...p, from: tr.changes.mapPos(p.from, 1), to: tr.changes.mapPos(p.to, -1) };
  },
  provide: (f) => EditorView.decorations.from(f, (p) => (p ? buildDecorations(p) : Decoration.none)),
});

export function acceptProposal(view) {
  const p = view.state.field(proposalField, false);
  if (!p) return false;
  if (p.mode === 'insert') return insertProposal(view);
  view.dispatch({
    changes: { from: p.from, to: p.to, insert: p.text },
    selection: { anchor: p.from + p.text.length },
    effects: clearProposal.of(null),
    userEvent: 'input.ai',
  });
  return true;
}

export function insertProposal(view) {
  const p = view.state.field(proposalField, false);
  if (!p) return false;
  const insert = `\n\n${p.text}`;
  view.dispatch({
    changes: { from: p.to, insert },
    selection: { anchor: p.to + insert.length },
    effects: clearProposal.of(null),
    userEvent: 'input.ai',
  });
  return true;
}

export function rejectProposal(view) {
  if (!view.state.field(proposalField, false)) return false;
  view.dispatch({ effects: clearProposal.of(null) });
  return true;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

class ProposalWidget extends WidgetType {
  constructor(p) { super(); this.p = p; }

  eq(other) { return other.p.text === this.p.text && other.p.mode === this.p.mode && other.p.label === this.p.label; }

  toDOM(view) {
    const wrap = el('div', 'sw-proposal');
    wrap.append(el('div', 'sw-proposal-head', `AI · ${this.p.label ?? 'suggestion'}`), el('pre', 'sw-proposal-text', this.p.text));
    const bar = el('div', 'sw-proposal-bar');
    const button = (label, fn, cls = '') => {
      const b = el('button', `sw-btn ${cls}`.trim(), label);
      b.type = 'button';
      b.addEventListener('mousedown', (e) => { e.preventDefault(); fn(view); });
      bar.append(b);
    };
    if (this.p.mode === 'replace') button('Accept', acceptProposal, 'sw-primary');
    button(this.p.mode === 'replace' ? 'Insert below' : 'Insert', insertProposal, this.p.mode === 'insert' ? 'sw-primary' : '');
    button('Reject', rejectProposal);
    wrap.append(bar);
    return wrap;
  }

  ignoreEvent() { return true; }
}

function buildDecorations(p) {
  const ranges = [];
  if (p.mode === 'replace' && p.to > p.from) ranges.push(Decoration.mark({ class: 'sw-del' }).range(p.from, p.to));
  ranges.push(Decoration.widget({ widget: new ProposalWidget(p), block: true, side: 1 }).range(p.to));
  return Decoration.set(ranges, true);
}

export const proposalExtension = [
  proposalField,
  keymap.of([{ key: 'Escape', run: rejectProposal }]),
];
```

`src/editor/context.js`:
```js
import { sceneRange } from '../fountain/outline.js';
import { analysisField } from './analysis.js';

/** What the AI needs from the editor: full text, parse, current scene, selection. */
export function editorContext(state) {
  const text = state.doc.toString();
  const sel = state.selection.main;
  const cursorLine = state.doc.lineAt(sel.head).number - 1;
  const { startLine, endLine } = sceneRange(text, cursorLine);
  const from = state.doc.line(startLine + 1).from;
  const to = state.doc.line(endLine + 1).to;
  return {
    text,
    elements: state.field(analysisField).elements,
    cursorLine,
    scene: { from, to, text: state.sliceDoc(from, to) },
    selection: { from: sel.from, to: sel.to, text: state.sliceDoc(sel.from, sel.to) },
  };
}
```

In `src/editor/setup.js`:
- Add `import { EditorView ... } ` (already imported) and `import { proposalExtension, showProposal } from './proposal.js';`.
- Add `proposalExtension,` to the extensions array, right after `decorations,`.
- Append:
```js
export function proposeEdit(view, proposal) {
  view.dispatch({ effects: [showProposal.of(proposal), EditorView.scrollIntoView(proposal.to, { y: 'center' })] });
}
```

Append this CSS to `appCss()` in `src/ui/styles.js`:
```css
.sw-del{text-decoration:line-through;background:rgba(224,108,117,.18)}
.sw-proposal{margin:.1667in 0;padding:10px 12px;border-left:3px solid var(--neon,#b8f25c);background:rgba(184,242,92,.10);font-family:system-ui,sans-serif;font-size:12px}
.sw-proposal-head{font-weight:600;margin-bottom:6px}
.sw-proposal-text{margin:0 0 8px;white-space:pre-wrap;font-family:'Courier Prime','Courier New',monospace;font-size:12pt;line-height:.1667in}
.sw-proposal-bar{display:flex;gap:6px}
```

- [ ] **Step 4: Run tests.** Run `npx vitest run src/editor`. Expected: PASS. If jsdom renders no `.sw-proposal`, keep the explicit `parent.style.height`. Don't change production code for jsdom.
- [ ] **Step 5: Commit** as "feat(script-writer): inline AI proposal widget + editor context".

---

### Task 5: Formatting toolbar, emphasis keys, + Scene

**Files:**
- Create: `src/editor/format.js`, `src/ui/FormatBar.jsx`
- Modify:
  - `src/editor/keymap.js`: Mod-b/i/u and Mod-k.
  - `src/editor/setup.js`: `onAi` option, and `onCursorLine(line0, type)`.
  - `src/ui/SceneNav.jsx`: a "+" button in the header.
  - `src/ui/EditorScreen.jsx`: format bar row, cursor type state, handlers.
  - `src/ui/styles.js`.
- Test: `src/editor/__tests__/format.test.js` (jsdom)

**Interfaces:**
- Consumes: `setType(type)`, `typeAt(state, lineNo1)` (commands.js), `setHint` (hints.js), `sceneInsertPos` (Task 2).
- Produces:
  - `MARKERS`, `toggleEmphasis(kind: 'bold'|'italic'|'underline') → Command`, and `insertSceneAfterCursor(view) → boolean`.
  - `<FormatBar currentType onSetType onEmphasis onNewScene/>`.
  - `scriptKeymap({onSave, onToggleFocus, onAi})`.
  - `createEditor({..., onAi})`.

- [ ] **Step 1: Write failing tests**

`src/editor/__tests__/format.test.js`:
```js
// @vitest-environment jsdom
import { EditorSelection, EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { describe, expect, it } from 'vitest';
import { analysisField } from '../analysis.js';
import { insertSceneAfterCursor, toggleEmphasis } from '../format.js';
import { hintField } from '../hints.js';

const run = (cmd, state) => { let s = state; cmd({ state, dispatch: (tr) => { s = tr.state; } }); return s; };
const st = (doc, sel) => EditorState.create({ doc, selection: sel, extensions: [analysisField, hintField] });

describe('toggleEmphasis', () => {
  it('wraps the selection and keeps it selected', () => {
    const s = run(toggleEmphasis('bold'), st('She runs fast.', EditorSelection.range(4, 8)));
    expect(s.doc.toString()).toBe('She **runs** fast.');
    expect(s.sliceDoc(s.selection.main.from, s.selection.main.to)).toBe('runs');
  });
  it('unwraps when the selection is already wrapped', () => {
    const s = run(toggleEmphasis('underline'), st('She _runs_ fast.', EditorSelection.range(5, 9)));
    expect(s.doc.toString()).toBe('She runs fast.');
  });
  it('does not treat bold as italic', () => {
    const s = run(toggleEmphasis('italic'), st('She **runs** fast.', EditorSelection.range(6, 10)));
    expect(s.doc.toString()).toBe('She ***runs*** fast.');
  });
  it('inserts a marker pair at an empty cursor', () => {
    const s = run(toggleEmphasis('italic'), st('Go', EditorSelection.cursor(2)));
    expect(s.doc.toString()).toBe('Go**');
    expect(s.selection.main.head).toBe(3);
  });
});

describe('insertSceneAfterCursor', () => {
  it('adds INT. after the current scene, before the next one', () => {
    const doc = 'INT. A - DAY\n\nHi.\n\nINT. B - DAY\n\nYo.';
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    const view = new EditorView({ state: st(doc, EditorSelection.cursor(15)), parent });
    expect(insertSceneAfterCursor(view)).toBe(true);
    expect(view.state.doc.toString()).toBe('INT. A - DAY\n\nHi.\n\nINT. \n\nINT. B - DAY\n\nYo.');
    expect(view.state.selection.main.head).toBe('INT. A - DAY\n\nHi.\n\nINT. '.length);
    view.destroy();
  });
});
```
In the second test the insert is `\n\nINT. ` at the end of "Hi.". The existing `\n\n` before the next heading stays, so the doc becomes `...Hi.\n\nINT. \n\nINT. B...`.

- [ ] **Step 2: Run to verify failure.** Run `npx vitest run src/editor/__tests__/format.test.js`. Expected: FAIL.

- [ ] **Step 3: Implement**

`src/editor/format.js`:
```js
import { startCompletion } from '@codemirror/autocomplete';
import { EditorSelection } from '@codemirror/state';
import { sceneInsertPos } from '../fountain/outline.js';
import { setHint } from './hints.js';

export const MARKERS = Object.freeze({ bold: '**', italic: '*', underline: '_' });

function wrappedBy(state, from, to, m) {
  if (state.sliceDoc(from - m.length, from) !== m || state.sliceDoc(to, to + m.length) !== m) return false;
  if (m !== '*') return true;
  // a single * next to another * is part of ** — not an italic wrapper
  return state.sliceDoc(from - 2, from - 1) !== '*' && state.sliceDoc(to + 1, to + 2) !== '*';
}

export const toggleEmphasis = (kind) => ({ state, dispatch }) => {
  const m = MARKERS[kind];
  const tr = state.changeByRange((range) => {
    if (!range.empty && wrappedBy(state, range.from, range.to, m)) {
      return {
        changes: [{ from: range.from - m.length, to: range.from }, { from: range.to, to: range.to + m.length }],
        range: EditorSelection.range(range.from - m.length, range.to - m.length),
      };
    }
    return {
      changes: [{ from: range.from, insert: m }, { from: range.to, insert: m }],
      range: EditorSelection.range(range.from + m.length, range.to + m.length),
    };
  });
  dispatch(state.update(tr, { userEvent: 'input.format', scrollIntoView: true }));
  return true;
};

export function insertSceneAfterCursor(view) {
  const { state } = view;
  const line0 = state.doc.lineAt(state.selection.main.head).number - 1;
  const at = sceneInsertPos(state.doc.toString(), line0);
  const insert = '\n\nINT. ';
  view.dispatch({
    changes: { from: at, insert },
    selection: { anchor: at + insert.length },
    effects: setHint.of({ pos: at + 2, type: 'scene_heading' }),
    scrollIntoView: true,
    userEvent: 'input.scene',
  });
  view.focus();
  startCompletion(view);
  return true;
}
```

`src/editor/keymap.js`: add these imports and entries. The signature becomes `scriptKeymap({ onSave, onToggleFocus, onAi } = {})`:
```js
import { toggleEmphasis } from './format.js';
// ...inside the keymap array, after Mod-Shift-f:
    { key: 'Mod-b', run: toggleEmphasis('bold'), preventDefault: true },
    { key: 'Mod-i', run: toggleEmphasis('italic'), preventDefault: true },
    { key: 'Mod-u', run: toggleEmphasis('underline'), preventDefault: true },
    { key: 'Mod-k', run: () => { onAi?.(); return true; }, preventDefault: true },
```

`src/editor/setup.js`:
- Add `import { typeAt } from './commands.js';`.
- Add `onAi` to the `createEditor` params and pass it as `scriptKeymap({ onSave, onToggleFocus, onAi })`.
- Change the updateListener cursor line to:
```js
        if (u.docChanged || u.selectionSet) {
          const line0 = u.state.doc.lineAt(u.state.selection.main.head).number - 1;
          onCursorLine?.(line0, typeAt(u.state, line0 + 1));
        }
```

`src/ui/FormatBar.jsx`:
```jsx
import { Plus } from 'lucide-react';

export const ELEMENT_OPTIONS = [
  ['scene_heading', 'Scene heading'], ['action', 'Action'], ['character', 'Character'],
  ['parenthetical', 'Parenthetical'], ['dialogue', 'Dialogue'], ['transition', 'Transition'], ['centered', 'Centered'],
];

// onMouseDown + preventDefault keeps the editor focus and selection intact.
const keep = (fn) => (e) => { e.preventDefault(); fn(); };

export function FormatBar({ currentType, onSetType, onEmphasis, onNewScene }) {
  const known = ELEMENT_OPTIONS.some(([v]) => v === currentType);
  return (
    <div className="sw-formatbar" role="toolbar" aria-label="Formatting">
      <select className="sw-btn" value={known ? currentType : ''} title={'Element (Tab or ⌘1–7)'}
        onChange={(e) => onSetType(e.target.value)}>
        {!known && <option value="" disabled>{currentType ? currentType.replace('_', ' ') : 'Element'}</option>}
        {ELEMENT_OPTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
      </select>
      <button type="button" className="sw-btn sw-fmt" title={'Bold (⌘B)'} onMouseDown={keep(() => onEmphasis('bold'))}><b>B</b></button>
      <button type="button" className="sw-btn sw-fmt" title={'Italic (⌘I)'} onMouseDown={keep(() => onEmphasis('italic'))}><i>I</i></button>
      <button type="button" className="sw-btn sw-fmt" title={'Underline (⌘U)'} onMouseDown={keep(() => onEmphasis('underline'))}><u>U</u></button>
      <span className="sw-sep" />
      <button type="button" className="sw-btn" title="New scene after this one" onMouseDown={keep(onNewScene)}><Plus size={14} />Scene</button>
    </div>
  );
}
```

`src/ui/SceneNav.jsx`: add an `onAdd` prop and replace the header div with:
```jsx
      <div className="sw-h sw-h-row">
        <span>Scenes &middot; {scenes.length}</span>
        {onAdd && <button type="button" className="sw-icon" title="New scene after the cursor" onMouseDown={(e) => { e.preventDefault(); onAdd(); }}>+</button>}
      </div>
```

`src/ui/EditorScreen.jsx` edits:
- **Imports:** add `import { typeAt, setType } from '../editor/commands.js';`, `import { insertSceneAfterCursor, toggleEmphasis } from '../editor/format.js';` and `import { FormatBar } from './FormatBar.jsx';`.
- **State:** add `const [cursorType, setCursorType] = useState(null);`.
- **createEditor call:**
  - Replace `onCursorLine: setCursorLine,` with `onCursorLine: (line0, type) => { setCursorLine(line0); setCursorType(type); },`.
  - Add `onAi: () => patchUi({ panel: 'ai' }),`. The AI panel arrives in Task 7; until then `'ai'` just hides the page view.
- **Helpers:** after `const jump = ...` add:
```jsx
  const withView = (fn) => () => { const v = viewRef.current; if (v) { fn(v); v.focus(); } };
  const onSetType = (type) => withView((v) => setType(type)(v))();
  const onEmphasis = (kind) => withView((v) => toggleEmphasis(kind)(v))();
  const onNewScene = withView((v) => insertSceneAfterCursor(v));
```
  `setType(type)` and `toggleEmphasis(kind)` are commands taking `{state, dispatch}`, and an `EditorView` satisfies that.
- **Format bar:** directly before `<div className="sw-body">` insert `<FormatBar currentType={cursorType} onSetType={onSetType} onEmphasis={onEmphasis} onNewScene={onNewScene} />`.
- **SceneNav:** pass `onAdd={onNewScene}`.

Append this CSS to `appCss()`:
```css
.sw-formatbar{display:flex;align-items:center;gap:6px;padding:6px 12px;border-bottom:1px solid var(--hairline,#2a2a2a)}
.sw-fmt{min-width:30px;justify-content:center}
.sw-sep{width:1px;align-self:stretch;background:var(--hairline,#2a2a2a);margin:0 4px}
.sw-h-row{display:flex;align-items:center;justify-content:space-between;padding-right:8px}
.sw-icon{background:none;border:1px solid var(--hairline,#2a2a2a);color:inherit;border-radius:4px;width:22px;height:22px;cursor:pointer;line-height:1}
```

- [ ] **Step 4: Run the full suite and build.** Run `npx vitest run && npm run build`. Expected: PASS, and the build succeeds. The existing setup smoke test must still pass, because `onCursorLine` gains a 2nd argument (backwards compatible).
- [ ] **Step 5: Commit** as "feat(script-writer): formatting toolbar, emphasis keys, + Scene".

---

### Task 6: Conversation threads in the plugin data dir

**Files:**
- Create: `src/main/threads.js`
- Modify: `src/main.js` (register `thread-read`, `thread-write`, `thread-clear`)
- Test: `src/main/__tests__/threads.test.js`

**Interfaces:**
- Produces:
  - `readThread(dataDir, key) → Message[]` (`[]` if missing or corrupt).
  - `writeThread(dataDir, {key, messages}) → true`, written atomically.
  - `clearThread(dataDir, key) → true`.
  - `Message = {role: 'user'|'assistant', text: string, error?, note?, sources?: [{n, path, title, snippet, content?}]}`.
  - The key regex is the same as drafts, `^[a-z0-9-]{1,120}$`. At most 200 messages; over that, throw.
  - IPC: `thread-read(key)`, `thread-write({key, messages})`, `thread-clear(key)`.

- [ ] **Step 1: Write failing tests**

`src/main/__tests__/threads.test.js`:
```js
import { mkdtempSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { clearThread, readThread, writeThread } from '../threads.js';

const dir = () => mkdtempSync(join(tmpdir(), 'sw-threads-'));
const M = [{ role: 'user', text: 'Who is Mara?' }, { role: 'assistant', text: 'Mara is 40 [1].', sources: [{ n: 1, path: 'a.md', title: 'Bio', snippet: 's' }] }];

describe('threads', () => {
  it('round-trips, clears, and leaves no tmp file', () => {
    const d = dir();
    expect(readThread(d, 'k')).toEqual([]);
    writeThread(d, { key: 'k', messages: M });
    expect(readThread(d, 'k')).toEqual(M);
    expect(readdirSync(join(d, 'threads'))).toEqual(['k.json']);
    clearThread(d, 'k');
    expect(readThread(d, 'k')).toEqual([]);
  });
  it('validates key, shape and size', () => {
    const d = dir();
    expect(() => writeThread(d, { key: '../x', messages: [] })).toThrow(/invalid thread key/);
    expect(() => writeThread(d, { key: 'k', messages: 'no' })).toThrow(/array/);
    expect(() => writeThread(d, { key: 'k', messages: [{ role: 'system', text: 'x' }] })).toThrow(/role/);
    expect(() => writeThread(d, { key: 'k', messages: Array.from({ length: 201 }, () => ({ role: 'user', text: 'x' })) })).toThrow(/200/);
  });
  it('treats a corrupt thread as empty', () => {
    const d = dir();
    mkdirSync(join(d, 'threads'));
    writeFileSync(join(d, 'threads', 'bad.json'), '{nope');
    expect(readThread(d, 'bad')).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify failure.** Expected: FAIL.

- [ ] **Step 3: Implement**

`src/main/threads.js`:
```js
import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const KEY = /^[a-z0-9-]{1,120}$/;
const MAX_MESSAGES = 200;

function threadFile(dataDir, key) {
  if (!KEY.test(String(key))) throw new Error(`invalid thread key: ${JSON.stringify(key)}`);
  return join(dataDir, 'threads', `${key}.json`);
}

export function readThread(dataDir, key) {
  try {
    const v = JSON.parse(readFileSync(threadFile(dataDir, key), 'utf-8'));
    return Array.isArray(v) ? v : [];
  } catch (e) {
    if (e.code === 'ENOENT' || e instanceof SyntaxError) return [];
    throw e;
  }
}

export function writeThread(dataDir, { key, messages } = {}) {
  const file = threadFile(dataDir, key);
  if (!Array.isArray(messages)) throw new Error('thread messages must be an array');
  if (messages.length > MAX_MESSAGES) throw new Error(`a thread holds at most ${MAX_MESSAGES} messages`);
  for (const m of messages) {
    if (!m || (m.role !== 'user' && m.role !== 'assistant')) throw new Error('each message needs role user|assistant');
    if (typeof m.text !== 'string') throw new Error('each message needs a text string');
  }
  mkdirSync(join(dataDir, 'threads'), { recursive: true });
  const tmp = `${file}.tmp`;
  writeFileSync(tmp, JSON.stringify(messages));
  renameSync(tmp, file);
  return true;
}

export function clearThread(dataDir, key) {
  rmSync(threadFile(dataDir, key), { force: true });
  return true;
}
```

`src/main.js`: import `{ clearThread, readThread, writeThread } from './main/threads.js'`, and in `activate` after the draft handlers add:
```js
  ctx.ipc.handle('thread-read', (key) => readThread(ctx.dataDir, key));
  ctx.ipc.handle('thread-write', (req) => writeThread(ctx.dataDir, req ?? {}));
  ctx.ipc.handle('thread-clear', (key) => clearThread(ctx.dataDir, key));
```

- [ ] **Step 4: Run tests and build.** Expected: PASS.
- [ ] **Step 5: Commit** as "feat(script-writer): persist AI conversation threads".

---

### Task 7: AI panel (Ask with citations, actions → inline proposals)

**Files:**
- Create: `src/ui/AiPanel.jsx`
- Modify:
  - `package.json`: add `"marked": "^12.0.0"` to dependencies, then `npm install`.
  - `src/ui/EditorScreen.jsx`: right-panel tabs, AI panel, `getContext`, `onPropose`, and a `focusToken` for ⌘K.
  - `src/ui/styles.js`.
- Test: `src/ui/__tests__/AiPanel.test.jsx` (jsdom)

**Interfaces:**
- Consumes: `retrieve`, `SCOPES` (Task 1); `runLlm`, `BUDGETS` (Task 1); `askPrompt`, `actionPrompt`, `outlineText`, `ACTIONS`, `REWRITE_PRESETS` (Task 2); `checkFountain` (Task 2); `editorContext` (Task 4); `proposeEdit` (Task 4); `draftKey` (existing); the thread IPC (Task 6).
- Produces:
  - `<AiPanel plugin scriptPath getContext onPropose notify focusToken/>`.
  - `renderAnswer(markdown) → html`, where `[n]` becomes `<button class="sw-cite" data-n="n">`.

- [ ] **Step 1: Write the failing test**

`src/ui/__tests__/AiPanel.test.jsx`:
```jsx
// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { AiPanel, renderAnswer } from '../AiPanel.jsx';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SCRIPT = '20-contexts/personal/projects/night/draft.screenplay.md';
const flush = () => act(() => new Promise((r) => setTimeout(r, 0)));

function fakePlugin({ llm }) {
  const calls = [];
  const threads = {};
  return {
    calls,
    threads,
    ipc: {
      invoke: async (ch, arg) => {
        if (ch === 'thread-read') return threads[arg] ?? [];
        if (ch === 'thread-write') { threads[arg.key] = arg.messages; return true; }
        return null;
      },
    },
    sidecar: {
      request: async (method, path, body) => {
        calls.push({ method, path, body });
        if (path === '/v1/search') {
          return { ok: true, data: { items: [
            { path: '20-contexts/personal/projects/night/mara.md', title: 'Mara bio', snippet: 'Mara is 40', score: 0.9 },
            { path: '20-contexts/personal/projects/night/town.md', title: 'Town', snippet: 'Foggy', score: 0.8 },
            { path: '20-contexts/personal/projects/night/joe.md', title: 'Joe', snippet: 'Joe lies', score: 0.7 },
          ] } };
        }
        if (path.startsWith('/v1/notes')) return { ok: true, data: { body: 'Mara is 40 and hates boats.' } };
        if (path === '/v1/llm/run') return { ok: true, data: llm(body) };
        return { ok: false, error: 'no route', status: 500 };
      },
    },
  };
}

const ctx = { text: 'INT. A - DAY\n\nMara waits.', elements: [], cursorLine: 2, scene: { from: 0, to: 25, text: 'INT. A - DAY\n\nMara waits.' }, selection: { from: 14, to: 14, text: '' } };

async function mount(plugin, props = {}) {
  const el = document.createElement('div');
  document.body.appendChild(el);
  const root = createRoot(el);
  await act(async () => { root.render(<AiPanel plugin={plugin} scriptPath={SCRIPT} getContext={() => ctx} onPropose={props.onPropose ?? (() => {})} notify={props.notify ?? (() => {})} focusToken={0} />); });
  await flush();
  return { el, root };
}

describe('renderAnswer', () => {
  it('renders markdown, drops raw html, and turns [n] into citation buttons', () => {
    const html = renderAnswer('**Mara** is 40 [1].<script>x</script>');
    expect(html).toContain('<strong>Mara</strong>');
    expect(html).toContain('<button type="button" class="sw-cite" data-n="1">[1]</button>');
    expect(html).not.toContain('<script>');
  });
});

describe('AiPanel', () => {
  it('asks: searches the project, answers with a clickable citation, persists the thread', async () => {
    const plugin = fakePlugin({ llm: () => ({ text: 'Mara is 40 [1].', structured: null, error: null }) });
    const { el, root } = await mount(plugin);
    const ta = el.querySelector('textarea');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set;
      setter.call(ta, 'How old is Mara?');
      ta.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => { el.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
    await flush();
    const llmCall = plugin.calls.find((c) => c.path === '/v1/llm/run');
    expect(llmCall.body.budgetUsd).toBe(1);
    expect(llmCall.body.prompt).toContain('[1] Mara bio');
    expect(el.textContent).toContain('Mara is 40');
    await act(async () => { el.querySelector('.sw-cite').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    expect(el.querySelector('.sw-source').textContent).toContain('Mara bio');
    expect(plugin.threads['20-contexts-personal-projects-night-draft-screenplay-md']).toHaveLength(2);
    act(() => root.unmount());
  });

  it('runs an action on the scene and proposes a replace edit', async () => {
    const onPropose = vi.fn();
    const plugin = fakePlugin({ llm: () => ({ text: '', structured: { fountain: 'INT. A - DAY\n\nMara paces.' }, error: null }) });
    const { el, root } = await mount(plugin, { onPropose });
    const select = el.querySelector('.sw-ai-actions select');
    await act(async () => { select.value = 'punchup'; select.dispatchEvent(new Event('change', { bubbles: true })); });
    await act(async () => { el.querySelector('.sw-ai-actions .sw-primary').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    await flush();
    expect(onPropose).toHaveBeenCalledWith({ from: 0, to: 25, text: 'INT. A - DAY\n\nMara paces.', mode: 'replace', label: 'Punch up dialogue' });
    act(() => root.unmount());
  });

  it('shows invalid AI output as a message instead of an edit', async () => {
    const onPropose = vi.fn();
    const plugin = fakePlugin({ llm: () => ({ text: '', structured: { fountain: '' }, error: null }) });
    const { el, root } = await mount(plugin, { onPropose });
    await act(async () => { el.querySelector('.sw-ai-actions .sw-primary').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    await flush();
    expect(onPropose).not.toHaveBeenCalled();
    expect(el.textContent).toContain("wasn't usable screenplay text");
    act(() => root.unmount());
  });

  it('surfaces provider errors inline', async () => {
    const plugin = fakePlugin({ llm: () => ({ text: '', structured: null, error: 'Budget exceeded' }) });
    const { el, root } = await mount(plugin);
    await act(async () => { el.querySelector('.sw-ai-actions .sw-primary').dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    await flush();
    expect(el.querySelector('.sw-err').textContent).toContain('Budget exceeded');
    act(() => root.unmount());
  });
});
```

- [ ] **Step 2: Run to verify failure.** Run `npm install && npx vitest run src/ui/__tests__/AiPanel.test.jsx`. Expected: FAIL.

- [ ] **Step 3: Implement**

`src/ui/AiPanel.jsx`:
```jsx
import { Send, Sparkles, Trash2 } from 'lucide-react';
import { marked } from 'marked';
import { useEffect, useRef, useState } from 'react';
import { BUDGETS, runLlm } from '../ai/llm.js';
import { ACTIONS, REWRITE_PRESETS, actionPrompt, askPrompt, outlineText } from '../ai/prompts.js';
import { retrieve, SCOPES } from '../ai/retrieve.js';
import { checkFountain } from '../ai/validate.js';
import { draftKey } from '../fountain/document.js';

// LLM and vault content is untrusted: markdown renders, raw HTML does not.
marked.use({ renderer: { html: () => '' } });

const MAX_THREAD = 100;
const FENCE = '```';
const SCOPE_LABEL = { project: 'This project', context: 'This context', vault: 'Whole vault' };
const WIDENED = 'Nothing in this project matched — searched the whole context.';

export function renderAnswer(text) {
  return String(marked.parse(String(text ?? '')))
    .replace(/\[(\d{1,2})\]/g, '<button type="button" class="sw-cite" data-n="$1">[$1]</button>');
}

const slim = (sources) => sources.map(({ n, path, title, snippet, content }) => ({
  n, path, title, snippet, ...(content ? { content: content.slice(0, 1500) } : {}),
}));
const plainLabel = (a) => a.label.replace('…', '');

export function AiPanel({ plugin, scriptPath, getContext, onPropose, notify, focusToken }) {
  const key = draftKey(scriptPath);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [scope, setScope] = useState('project');
  const [busy, setBusy] = useState(null);
  const [actionId, setActionId] = useState('continue');
  const [direction, setDirection] = useState('');
  const [openSource, setOpenSource] = useState(null);
  const latest = useRef([]);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const action = ACTIONS.find((a) => a.id === actionId);

  useEffect(() => {
    let live = true;
    plugin.ipc.invoke('thread-read', key).then((m) => {
      if (live && Array.isArray(m)) { latest.current = m; setMessages(m); }
    }).catch(() => {});
    return () => { live = false; };
  }, [plugin, key]);
  useEffect(() => { inputRef.current?.focus(); }, [focusToken]);
  useEffect(() => { const l = listRef.current; if (l) l.scrollTop = l.scrollHeight; }, [messages, busy]);

  const push = (msgs) => {
    const kept = msgs.slice(-MAX_THREAD);
    latest.current = kept;
    setMessages(kept);
    plugin.ipc.invoke('thread-write', { key, messages: kept }).catch(() => {});
  };

  async function ask(e) {
    e?.preventDefault?.();
    const question = input.trim();
    if (!question || busy) return;
    const history = latest.current;
    const withQ = [...history, { role: 'user', text: question }];
    push(withQ);
    setInput('');
    setBusy('Searching your vault…');
    try {
      const ctx = getContext();
      const r = await retrieve(plugin, { query: question, scriptPath, scope });
      setBusy('Thinking…');
      const { system, prompt } = askPrompt({ question, outline: outlineText(ctx.elements), scene: ctx.scene.text, sources: r.sources, history });
      const out = await runLlm(plugin, { system, prompt, budgetUsd: BUDGETS.ask });
      push([...withQ, { role: 'assistant', text: out.text, sources: slim(r.sources), ...(r.widened ? { note: WIDENED } : {}) }]);
    } catch (err) {
      push([...withQ, { role: 'assistant', text: '', error: err.message }]);
    } finally {
      setBusy(null);
    }
  }

  async function runAction() {
    if (busy) return;
    const ctx = getContext();
    const target = ctx.selection.text.trim() ? ctx.selection : ctx.scene;
    if (!target.text.trim()) { notify('Put the cursor in a scene or select some text first.', 'error'); return; }
    if (action.needsDirection && !direction.trim()) { notify('Say how to rewrite it, or pick a preset.', 'error'); return; }
    const request = { role: 'user', text: `${plainLabel(action)}${direction.trim() && action.needsDirection ? `: ${direction.trim()}` : ''}` };
    const base = [...latest.current, request];
    setBusy(`${plainLabel(action)}…`);
    try {
      const r = await retrieve(plugin, { query: target.text.slice(0, 500), scriptPath, scope });
      const { system, prompt, jsonSchema } = actionPrompt({
        action, direction: action.needsDirection ? direction.trim() : '', target: target.text, outline: outlineText(ctx.elements), sources: r.sources,
      });
      const out = await runLlm(plugin, { system, prompt, jsonSchema, budgetUsd: BUDGETS.action });
      if (action.edits === 'none') {
        push([...base, { role: 'assistant', text: out.text, sources: slim(r.sources) }]);
        return;
      }
      const check = checkFountain(target.text, out.structured?.fountain, { minKeep: 0 });
      if (!check.ok) {
        push([...base, { role: 'assistant', text: `That suggestion wasn't usable screenplay text (${check.reason}), so it wasn't applied.${check.text ? `\n\n${FENCE}\n${check.text}\n${FENCE}` : ''}` }]);
        return;
      }
      const insert = action.edits === 'insert';
      onPropose({ from: insert ? target.to : target.from, to: target.to, text: check.text, mode: action.edits, label: plainLabel(action) });
      push([...base, { role: 'assistant', text: out.structured?.notes || 'Suggestion shown in the script — accept or reject it there.' }]);
    } catch (err) {
      push([...base, { role: 'assistant', text: '', error: err.message }]);
    } finally {
      setBusy(null);
    }
  }

  function onListClick(e) {
    const n = e.target?.dataset?.n;
    const holder = e.target?.closest?.('[data-msg]');
    if (!n || !holder) return;
    const id = `${holder.dataset.msg}:${n}`;
    setOpenSource((cur) => (cur === id ? null : id));
  }

  return (
    <div className="sw-ai">
      <div className="sw-ai-head">
        <Sparkles size={14} /><strong>AI co-writer</strong><span className="sw-grow" />
        <select className="sw-btn" value={scope} onChange={(e) => setScope(e.target.value)} title="Where to look in your vault">
          {SCOPES.map((s) => <option key={s} value={s}>{SCOPE_LABEL[s]}</option>)}
        </select>
        <button type="button" className="sw-btn" title="Clear conversation" onClick={() => push([])}><Trash2 size={14} /></button>
      </div>
      <div className="sw-ai-actions">
        <select className="sw-btn" value={actionId} onChange={(e) => setActionId(e.target.value)} title="Works on the selection, or the scene at the cursor">
          {ACTIONS.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
        </select>
        <button type="button" className="sw-btn sw-primary" disabled={!!busy} onClick={runAction}>Run</button>
        {action.needsDirection && (
          <div className="sw-ai-dir">
            <input value={direction} onChange={(e) => setDirection(e.target.value)} placeholder={'How? e.g. tighter, darker…'} />
            <div className="sw-chips">
              {REWRITE_PRESETS.map((p) => <button type="button" key={p} className="sw-chip" onClick={() => setDirection(p)}>{p}</button>)}
            </div>
          </div>
        )}
      </div>
      <div className="sw-ai-list" ref={listRef} onClick={onListClick}>
        {messages.length === 0 && (
          <p className="sw-muted">Ask anything about your story &mdash; the AI searches this project&rsquo;s notes first. Or pick an action above to work on the scene at your cursor.</p>
        )}
        {messages.map((m, i) => {
          const open = openSource?.startsWith(`${i}:`) ? m.sources?.find((s) => String(s.n) === openSource.split(':')[1]) : null;
          return (
            <div key={i} data-msg={i} className={`sw-msg sw-msg-${m.role}`}>
              {m.role === 'user' && <div>{m.text}</div>}
              {m.role === 'assistant' && m.error && <div className="sw-status sw-err">{m.error}</div>}
              {m.role === 'assistant' && !m.error && <div className="sw-md" dangerouslySetInnerHTML={{ __html: renderAnswer(m.text) }} />}
              {m.note && <div className="sw-muted">{m.note}</div>}
              {open && (
                <div className="sw-source">
                  <strong>[{open.n}] {open.title}</strong>
                  <div className="sw-muted">{open.path}</div>
                  <pre>{open.content ?? open.snippet}</pre>
                </div>
              )}
            </div>
          );
        })}
        {busy && <div className="sw-muted sw-busy">{busy}</div>}
      </div>
      <form className="sw-ai-input" onSubmit={ask}>
        <textarea ref={inputRef} rows={3} value={input} onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); } }}
          placeholder={'Ask about your story, characters, research…'} />
        <button type="submit" className="sw-btn sw-primary" disabled={!!busy || !input.trim()} title="Ask"><Send size={14} /></button>
      </form>
    </div>
  );
}
```

`src/ui/EditorScreen.jsx` edits:
- **Imports:**
  - Add `Sparkles` to the lucide import list.
  - Add `import { editorContext } from '../editor/context.js';` and `import { AiPanel } from './AiPanel.jsx';`.
  - Add `proposeEdit` to the `../editor/setup.js` import.
- **State:** add `const [aiFocus, setAiFocus] = useState(0);`.
- **createEditor:** change `onAi` to `onAi: () => { patchUi({ panel: 'ai' }); setAiFocus((n) => n + 1); },`.
- **Callbacks:** after `withView` add:
```jsx
  const getContext = useCallback(() => editorContext(viewRef.current.state), []);
  const onPropose = useCallback((p) => { const v = viewRef.current; if (v) proposeEdit(v, p); }, []);
```
- **Top bar:** after the Eye (page view) button add:
```jsx
        <button type="button" className={`sw-btn${ui.panel === 'ai' ? ' sw-on' : ''}`} onClick={() => patchUi({ panel: ui.panel === 'ai' ? null : 'ai' })} title={'AI co-writer (⌘K)'}><Sparkles size={14} /></button>
```
- **Right panel:** after the page-view `aside` add:
```jsx
        {ui.panel === 'ai' && (
          <aside className="sw-right sw-right-ai">
            <AiPanel plugin={plugin} scriptPath={path} getContext={getContext} onPropose={onPropose} notify={notify} focusToken={aiFocus} />
          </aside>
        )}
```

Append this CSS to `appCss()`:
```css
.sw-right-ai{display:flex;flex-direction:column;background:var(--paper,#121212)}
.sw-ai{display:flex;flex-direction:column;height:100%;min-height:0}
.sw-ai-head,.sw-ai-actions{display:flex;align-items:center;gap:6px;padding:8px 12px;border-bottom:1px solid var(--hairline,#2a2a2a);flex-wrap:wrap}
.sw-ai-dir{flex-basis:100%;display:flex;flex-direction:column;gap:6px}
.sw-ai-dir input,.sw-ai-input textarea{padding:6px 8px;border-radius:6px;border:1px solid var(--hairline,#2a2a2a);background:var(--vellum,#1a1a1a);color:inherit;font:inherit}
.sw-chips{display:flex;gap:6px;flex-wrap:wrap}
.sw-chip{border:1px solid var(--hairline,#2a2a2a);background:none;color:inherit;border-radius:999px;padding:2px 10px;cursor:pointer;font:inherit;font-size:12px}
.sw-ai-list{flex:1;overflow:auto;padding:12px;display:flex;flex-direction:column;gap:10px}
.sw-msg{padding:8px 10px;border-radius:8px;max-width:100%}
.sw-msg-user{align-self:flex-end;background:var(--vellum,#1a1a1a)}
.sw-msg-assistant{border:1px solid var(--hairline,#2a2a2a)}
.sw-md p{margin:.3em 0}.sw-md pre{white-space:pre-wrap;font-family:'Courier Prime','Courier New',monospace}
.sw-cite{border:none;background:none;color:var(--neon,#b8f25c);cursor:pointer;padding:0 1px;font:inherit}
.sw-source{margin-top:8px;padding:8px;border-left:2px solid var(--neon,#b8f25c);background:var(--vellum,#1a1a1a)}
.sw-source pre{white-space:pre-wrap;max-height:240px;overflow:auto;margin:6px 0 0;font:12px/1.4 system-ui,sans-serif}
.sw-ai-input{display:flex;gap:6px;padding:8px 12px;border-top:1px solid var(--hairline,#2a2a2a)}
.sw-ai-input textarea{flex:1;resize:vertical}
```

- [ ] **Step 4: Run the full suite and build.** Run `npx vitest run && npm run build`. Expected: PASS. If `act` warnings are printed, make them go away with the `IS_REACT_ACT_ENVIRONMENT` flag, which is already in the test. Don't silence real errors.
- [ ] **Step 5: Commit** `package.json`, `package-lock.json` and src as "feat(script-writer): AI co-writer panel — vault-grounded ask + inline actions".

---

### Task 8: Polish engine

**Files:**
- Create: `src/ai/polish.js`
- Test: `src/ai/__tests__/polish.test.js`

**Interfaces:**
- Consumes: `sceneBlocks`, `joinBlocks`, `characters` (outline); `parse`; `runLlm`, `BUDGETS`; `polishPrompt`; `checkFountain`; `hunks`, `applyHunks`.
- Produces:
  - `POLISH_CONCURRENCY = 3`.
  - `polishUnits(text) → {sb, units: Unit[]}`, where `Unit = {kind: 'pre'|'scene', index, heading, text}`.
  - `polishDocument(plugin, {text, passes, budgetPerSection?, concurrency?, onProgress?, signal?}) → {sb, results: Result[]}`, with `Result = Unit & {polished, status: 'changed'|'unchanged'|'rejected'|'error', reason?, summary?}`.
  - `composePolished({sb, results}, decide: (unitIndex, changeIndex) => boolean) → string`.

- [ ] **Step 1: Write failing tests**

`src/ai/__tests__/polish.test.js`:
```js
import { describe, expect, it } from 'vitest';
import { composePolished, polishDocument, polishUnits } from '../polish.js';

const DOC = 'FADE IN:\n\nINT. A - DAY\n\nmara wait.\n\nMARA\nNow?\n\nINT. B - DAY\n\nJoe run.\n\nJOE\nGo!\n\nINT. C - DAY\n\nOne.\nTwo.\nThree.\nFour.\nFive.\nSix.\n';

function fakePlugin(handler) {
  let inFlight = 0;
  const stats = { max: 0, calls: 0 };
  return {
    stats,
    sidecar: {
      request: async (method, path, body) => {
        stats.calls++;
        inFlight++;
        stats.max = Math.max(stats.max, inFlight);
        await new Promise((r) => setTimeout(r, 5));
        inFlight--;
        const section = body.prompt.split('## Section\n')[1];
        return handler(section, body);
      },
    },
  };
}

describe('polishUnits', () => {
  it('makes one unit for the preamble and one per scene', () => {
    const { units } = polishUnits(DOC);
    expect(units.map((u) => [u.kind, u.heading])).toEqual([['pre', 'Opening'], ['scene', 'INT. A - DAY'], ['scene', 'INT. B - DAY'], ['scene', 'INT. C - DAY']]);
  });
});

describe('polishDocument', () => {
  it('polishes every section with at most 3 in flight, keeping order and flagging failures', async () => {
    const plugin = fakePlugin((section, body) => {
      expect(body.budgetUsd).toBe(0.5);
      if (section.startsWith('INT. A')) return { ok: true, data: { text: '', structured: { fountain: 'INT. A - DAY\n\nMara waits.\n\nMARA\nNow?', changes: 'grammar' }, error: null } };
      if (section.startsWith('INT. B')) return { ok: true, data: { text: '', structured: null, error: 'Budget exceeded' } };
      if (section.startsWith('INT. C')) return { ok: true, data: { text: '', structured: { fountain: 'INT. C - DAY\n\nOne.' }, error: null } };
      return { ok: true, data: { text: '', structured: { fountain: section.trim() }, error: null } };
    });
    const progress = [];
    const out = await polishDocument(plugin, { text: DOC, passes: ['formatting', 'language'], onProgress: (p) => progress.push(p) });
    expect(plugin.stats.max).toBeLessThanOrEqual(3);
    expect(out.results.map((r) => r.status)).toEqual(['unchanged', 'changed', 'error', 'rejected']);
    expect(out.results[2].reason).toBe('Budget exceeded');
    expect(out.results[3].reason).toMatch(/lost/);
    expect(out.results[1].summary).toBe('grammar');
    expect(progress.at(-1)).toEqual({ done: 4, total: 4 });
  });
  it('requires at least one pass and honours cancellation', async () => {
    await expect(polishDocument(fakePlugin(() => ({})), { text: DOC, passes: [] })).rejects.toThrow(/at least one/);
    const ctrl = new AbortController();
    ctrl.abort();
    await expect(polishDocument(fakePlugin(() => ({})), { text: DOC, passes: ['language'], signal: ctrl.signal })).rejects.toThrow(/cancelled/);
  });
});

describe('composePolished', () => {
  const result = {
    sb: polishUnits(DOC).sb,
    results: polishUnits(DOC).units.map((u) => ({ ...u, polished: u.text, status: 'unchanged' })),
  };
  result.results[1] = { ...result.results[1], polished: 'INT. A - DAY\n\nMara waits.\n\nMARA\nNow?\n\nShe sits.', status: 'changed' };
  it('all on = polished, all off = original, partial = exact mix', () => {
    const all = composePolished(result, () => true);
    expect(all).toContain('Mara waits.\n\nMARA\nNow?\n\nShe sits.');
    expect(composePolished(result, () => false)).toBe(DOC);
    const first = composePolished(result, (u, c) => u === 1 && c === 0);
    expect(first).toContain('Mara waits.\n\nMARA\nNow?\n\nINT. B');
    expect(first).not.toContain('She sits.');
  });
});
```

- [ ] **Step 2: Run to verify failure.** Expected: FAIL.

- [ ] **Step 3: Implement**

`src/ai/polish.js`:
```js
// Whole-document polish, run per section so long scripts fit and one bad
// section never sinks the rest. Review/compose happens on line hunks.
import { applyHunks, hunks } from '../diff/lineDiff.js';
import { characters, joinBlocks, sceneBlocks } from '../fountain/outline.js';
import { parse } from '../fountain/parse.js';
import { BUDGETS, runLlm } from './llm.js';
import { polishPrompt } from './prompts.js';
import { checkFountain } from './validate.js';

export const POLISH_CONCURRENCY = 3;

export function polishUnits(text) {
  const sb = sceneBlocks(text);
  const units = [];
  if (sb.pre.trim()) units.push({ kind: 'pre', index: -1, heading: 'Opening', text: sb.pre });
  sb.blocks.forEach((b, i) => units.push({ kind: 'scene', index: i, heading: b.text.split('\n')[0].trim(), text: b.text }));
  return { sb, units };
}

export async function polishDocument(plugin, {
  text, passes, budgetPerSection = BUDGETS.polishPerSection, concurrency = POLISH_CONCURRENCY, onProgress = () => {}, signal,
}) {
  if (!passes?.length) throw new Error('Pick at least one polish pass');
  if (signal?.aborted) throw new Error('Polish cancelled');
  const { sb, units } = polishUnits(text);
  const names = characters(parse(text)).map((c) => c.name);
  const results = new Array(units.length);
  let next = 0;
  let done = 0;

  async function worker() {
    while (next < units.length && !signal?.aborted) {
      const k = next++;
      const unit = units[k];
      try {
        const { system, prompt, jsonSchema } = polishPrompt({ passes, sceneText: unit.text, characterNames: names });
        const out = await runLlm(plugin, { system, prompt, jsonSchema, budgetUsd: budgetPerSection });
        const check = checkFountain(unit.text, out.structured?.fountain, { minKeep: 0.6, keepHeading: unit.kind === 'scene' });
        results[k] = check.ok
          ? { ...unit, polished: check.text, status: check.text === unit.text ? 'unchanged' : 'changed', summary: out.structured?.changes ?? '' }
          : { ...unit, polished: unit.text, status: 'rejected', reason: check.reason };
      } catch (err) {
        results[k] = { ...unit, polished: unit.text, status: 'error', reason: err.message };
      }
      done++;
      onProgress({ done, total: units.length });
    }
  }

  await Promise.all(Array.from({ length: Math.max(1, Math.min(concurrency, units.length)) }, worker));
  if (signal?.aborted) throw new Error('Polish cancelled');
  return { sb, results };
}

export function composePolished({ sb, results }, decide) {
  const texts = results.map((r, u) => {
    if (r.status !== 'changed') return r.text;
    return applyHunks(hunks(r.text.split('\n'), r.polished.split('\n')), (c) => decide(u, c)).join('\n');
  });
  const offset = results[0]?.kind === 'pre' ? 1 : 0;
  return joinBlocks({
    ...sb,
    pre: offset ? texts[0] : sb.pre,
    blocks: sb.blocks.map((b, i) => ({ ...b, text: texts[i + offset] })),
  });
}
```

- [ ] **Step 4: Run tests.** Run `npx vitest run src/ai`. Expected: PASS.

  The all-off test asserts `composePolished(..., () => false) === DOC`. That holds because DOC is already normalised: one blank line between blocks and a trailing newline. If it fails, check `joinBlocks` and `sceneBlocks` before changing the test.
- [ ] **Step 5: Commit** as "feat(script-writer): whole-document polish engine".

---

### Task 9: Polish dialog and whole-document review

**Files:**
- Create: `src/ui/PolishDialog.jsx`, `src/ui/PolishReview.jsx`
- Modify: `src/ui/EditorScreen.jsx` (Polish button, polish state, apply), `src/ui/styles.js`
- Test: `src/ui/__tests__/PolishReview.test.jsx` (jsdom)

**Interfaces:**
- Consumes: `polishUnits`, `polishDocument`, `composePolished`, `POLISH_CONCURRENCY` (Task 8); `POLISH_PASSES` (Task 2); `hunks`, `wordDiff` (Task 3); `BUDGETS` (Task 1).
- Produces: `<PolishDialog plugin text onDone(result) onCancel/>` and `<PolishReview result onApply(text) onClose/>`.

- [ ] **Step 1: Write the failing test**

`src/ui/__tests__/PolishReview.test.jsx`:
```jsx
// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { polishUnits } from '../../ai/polish.js';
import { PolishReview } from '../PolishReview.jsx';

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const DOC = 'INT. A - DAY\n\nmara wait.\n\nMARA\nNow?\n\nINT. B - DAY\n\nGo.\n';

function makeResult() {
  const { sb, units } = polishUnits(DOC);
  const results = units.map((u) => ({ ...u, polished: u.text, status: 'unchanged' }));
  results[0] = { ...results[0], status: 'changed', summary: 'grammar', polished: 'INT. A - DAY\n\nMara waits.\n\nMARA\nNow?\n\nShe sits.' };
  results[1] = { ...results[1], status: 'error', reason: 'Budget exceeded' };
  return { sb, results };
}

describe('PolishReview', () => {
  it('lists changes and flags, and applies only the kept changes', async () => {
    const onApply = vi.fn();
    const el = document.createElement('div');
    document.body.appendChild(el);
    const root = createRoot(el);
    await act(async () => { root.render(<PolishReview result={makeResult()} onApply={onApply} onClose={() => {}} />); });
    expect(el.textContent).toContain('2 changes');
    expect(el.textContent).toContain('Budget exceeded');
    const boxes = el.querySelectorAll('input[type=checkbox]');
    expect(boxes).toHaveLength(2);
    await act(async () => { boxes[1].click(); });
    await act(async () => { [...el.querySelectorAll('button')].find((b) => b.textContent === 'Apply').click(); });
    expect(onApply).toHaveBeenCalledWith('INT. A - DAY\n\nMara waits.\n\nMARA\nNow?\n\nINT. B - DAY\n\nGo.\n');
    act(() => root.unmount());
  });
});
```

- [ ] **Step 2: Run to verify failure.** Expected: FAIL.

- [ ] **Step 3: Implement**

`src/ui/PolishReview.jsx`:
```jsx
import { useMemo, useState } from 'react';
import { composePolished } from '../ai/polish.js';
import { hunks, wordDiff } from '../diff/lineDiff.js';

function Words({ a, b }) {
  return (
    <>
      <div className="sw-pl-del">{wordDiff(a, b).filter((p) => p.type !== 'add').map((p, i) => <span key={i} className={p.type === 'del' ? 'sw-w-del' : ''}>{p.text}</span>)}</div>
      <div className="sw-pl-add">{wordDiff(a, b).filter((p) => p.type !== 'del').map((p, i) => <span key={i} className={p.type === 'add' ? 'sw-w-add' : ''}>{p.text}</span>)}</div>
    </>
  );
}

export function PolishReview({ result, onApply, onClose }) {
  const items = useMemo(() => result.results.map((r, u) => ({
    r, u, hs: r.status === 'changed' ? hunks(r.text.split('\n'), r.polished.split('\n')) : [],
  })), [result]);
  const keys = useMemo(() => items.flatMap(({ u, hs }) => hs.filter((h) => h.type === 'change').map((_, c) => `${u}:${c}`)), [items]);
  const [off, setOff] = useState(() => new Set());
  const flagged = items.filter(({ r }) => r.status === 'rejected' || r.status === 'error');
  const toggle = (k) => setOff((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const apply = () => onApply(composePolished(result, (u, c) => !off.has(`${u}:${c}`)));

  return (
    <div className="sw-modal" role="dialog" aria-label="Polish review">
      <div className="sw-dialog sw-polish-review">
        <div className="sw-row" style={{ justifyContent: 'space-between', marginTop: 0 }}>
          <h2 style={{ margin: 0 }}>Polish review</h2>
          <span className="sw-muted">{keys.length} changes &middot; {keys.length - off.size} kept</span>
        </div>
        {flagged.length > 0 && (
          <div className="sw-pl-flags">
            {flagged.map(({ r, u }) => <div key={u} className="sw-status sw-err">{r.heading}: kept original ({r.reason})</div>)}
          </div>
        )}
        {keys.length === 0 && <p className="sw-muted">Nothing to change &mdash; the script already reads clean for the passes you picked.</p>}
        <div className="sw-pl-list">
          {items.filter(({ hs }) => hs.length).map(({ r, u, hs }) => {
            let c = -1;
            return (
              <section key={u} className="sw-pl-scene">
                <h3>{r.heading}{r.summary ? <span className="sw-muted"> &mdash; {r.summary}</span> : null}</h3>
                {hs.map((h, i) => {
                  if (h.type === 'equal') return h.lines.length > 2 ? <div key={i} className="sw-pl-eq sw-muted">&hellip; {h.lines.length} unchanged lines</div> : <div key={i} className="sw-pl-eq">{h.lines.join('\n')}</div>;
                  c += 1;
                  const k = `${u}:${c}`;
                  return (
                    <label key={i} className={`sw-pl-hunk${off.has(k) ? ' sw-pl-off' : ''}`}>
                      <input type="checkbox" checked={!off.has(k)} onChange={() => toggle(k)} />
                      <div className="sw-pl-body">
                        {h.del.length === 1 && h.add.length === 1 ? <Words a={h.del[0]} b={h.add[0]} /> : (
                          <>
                            {h.del.length > 0 && <div className="sw-pl-del">{h.del.join('\n')}</div>}
                            {h.add.length > 0 && <div className="sw-pl-add">{h.add.join('\n')}</div>}
                          </>
                        )}
                      </div>
                    </label>
                  );
                })}
              </section>
            );
          })}
        </div>
        <div className="sw-row">
          <button type="button" className="sw-btn" onClick={() => setOff(new Set())}>Accept all</button>
          <button type="button" className="sw-btn" onClick={() => setOff(new Set(keys))}>Reject all</button>
          <span className="sw-grow" />
          <button type="button" className="sw-btn" onClick={onClose}>Close</button>
          <button type="button" className="sw-btn sw-primary" disabled={keys.length === 0} onClick={apply}>Apply</button>
        </div>
      </div>
    </div>
  );
}
```

`src/ui/PolishDialog.jsx`:
```jsx
import { useEffect, useMemo, useRef, useState } from 'react';
import { BUDGETS } from '../ai/llm.js';
import { polishDocument, polishUnits } from '../ai/polish.js';
import { POLISH_PASSES } from '../ai/prompts.js';

export function PolishDialog({ plugin, text, onDone, onCancel }) {
  const [passes, setPasses] = useState(() => POLISH_PASSES.filter((p) => p.default).map((p) => p.id));
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  const ctrl = useRef(null);
  const sections = useMemo(() => polishUnits(text).units.length, [text]);
  useEffect(() => () => ctrl.current?.abort(), []);

  const toggle = (id) => setPasses((ps) => (ps.includes(id) ? ps.filter((p) => p !== id) : [...ps, id]));

  async function run() {
    setError(null);
    ctrl.current = new AbortController();
    setProgress({ done: 0, total: sections });
    try {
      const result = await polishDocument(plugin, { text, passes, onProgress: setProgress, signal: ctrl.current.signal });
      onDone(result);
    } catch (err) {
      if (!ctrl.current?.signal.aborted) setError(err.message);
      setProgress(null);
    }
  }

  function cancel() {
    ctrl.current?.abort();
    onCancel();
  }

  return (
    <div className="sw-modal" role="dialog" aria-label="Polish">
      <div className="sw-dialog">
        <h2 style={{ marginTop: 0 }}>Polish script</h2>
        {POLISH_PASSES.map((p) => (
          <label key={p.id} className="sw-pl-pass">
            <input type="checkbox" checked={passes.includes(p.id)} disabled={!!progress} onChange={() => toggle(p.id)} />
            <span><strong>{p.label}</strong><br /><span className="sw-muted">{p.rule}</span></span>
          </label>
        ))}
        <p className="sw-muted">
          {sections} {sections === 1 ? 'section' : 'sections'} &middot; {sections} AI calls, at most ${(sections * BUDGETS.polishPerSection).toFixed(2)} &middot; you review every change before it lands
        </p>
        {progress && (
          <div className="sw-progress" aria-label="Polish progress">
            <div style={{ width: `${Math.round((100 * progress.done) / Math.max(1, progress.total))}%` }} />
            <span className="sw-muted">{progress.done} / {progress.total}</span>
          </div>
        )}
        {error && <div className="sw-status sw-err">{error}</div>}
        <div className="sw-row">
          <button type="button" className="sw-btn" onClick={cancel}>Cancel</button>
          <button type="button" className="sw-btn sw-primary" disabled={!!progress || passes.length === 0} onClick={run}>{progress ? 'Polishing…' : 'Polish'}</button>
        </div>
      </div>
    </div>
  );
}
```
The `${...}` inside JSX text renders a literal "$" followed by the value. That's intended.

`src/ui/EditorScreen.jsx` edits:
- **Imports:** add `WandSparkles` to the lucide imports, and `import { PolishDialog } from './PolishDialog.jsx';` and `import { PolishReview } from './PolishReview.jsx';`. If `WandSparkles` doesn't exist in the installed lucide-react, use `Wand2`; check with `grep -o "WandSparkles\|Wand2" node_modules/lucide-react/dist/esm/lucide-react.js | sort -u`.
- **State:** add `const [polish, setPolish] = useState(null); // null | {stage:'dialog'|'review', startText, result?}`.
- **Top bar:** before the Export menu add:
```jsx
        <button type="button" className="sw-btn" onClick={() => setPolish({ stage: 'dialog', startText: viewRef.current.state.doc.toString() })} title="Polish the whole script with AI"><WandSparkles size={14} />Polish</button>
```
- **Apply function:** add near `restoreDraft`:
```jsx
  function applyPolish(text) {
    const view = viewRef.current;
    const current = view.state.doc.toString();
    if (current !== polish.startText) {
      notify('The script changed while polishing — run Polish again so nothing you typed is overwritten.', 'error');
      setPolish(null);
      return;
    }
    view.dispatch({ changes: { from: 0, to: current.length, insert: text }, userEvent: 'input.polish' });
    setPolish(null);
    notify('Polish applied — ⌘Z to undo.');
  }
```
- **Render:** at the end of the fragment, next to the title-page modal, add:
```jsx
      {polish?.stage === 'dialog' && (
        <PolishDialog plugin={plugin} text={polish.startText} onCancel={() => setPolish(null)}
          onDone={(result) => setPolish((p) => ({ ...p, stage: 'review', result }))} />
      )}
      {polish?.stage === 'review' && <PolishReview result={polish.result} onApply={applyPolish} onClose={() => setPolish(null)} />}
```

Append this CSS to `appCss()`:
```css
.sw-polish-review{width:min(920px,95%);max-height:92%;display:flex;flex-direction:column}
.sw-pl-list{overflow:auto;flex:1;margin:12px 0;display:flex;flex-direction:column;gap:14px}
.sw-pl-scene h3{margin:0 0 6px;font-size:13px}
.sw-pl-eq{white-space:pre-wrap;font-family:'Courier Prime','Courier New',monospace;font-size:12px;opacity:.7;padding-left:26px}
.sw-pl-hunk{display:flex;gap:8px;align-items:flex-start;padding:4px 0;cursor:pointer}
.sw-pl-off .sw-pl-body{opacity:.4}
.sw-pl-body{flex:1;font-family:'Courier Prime','Courier New',monospace;font-size:12px;white-space:pre-wrap}
.sw-pl-del{background:rgba(224,108,117,.14);text-decoration:line-through;padding:2px 6px}
.sw-pl-add{background:rgba(184,242,92,.14);padding:2px 6px}
.sw-w-del{background:rgba(224,108,117,.45)}.sw-w-add{background:rgba(184,242,92,.45)}
.sw-pl-del .sw-w-del{text-decoration:line-through}.sw-pl-add{text-decoration:none}
.sw-pl-flags{display:flex;flex-direction:column;gap:4px;margin-top:8px}
.sw-pl-pass{display:flex;gap:10px;align-items:flex-start;margin:8px 0;cursor:pointer}
.sw-progress{position:relative;height:18px;border-radius:9px;background:var(--vellum,#1a1a1a);overflow:hidden;margin:8px 0}
.sw-progress>div{position:absolute;inset:0 auto 0 0;background:var(--neon,#b8f25c);opacity:.5}
.sw-progress>span{position:relative;padding-left:8px;font-size:12px}
```

- [ ] **Step 4: Run the full suite and build.** Expected: PASS.
- [ ] **Step 5: Commit** as "feat(script-writer): Polish dialog + whole-document review".

---

### Task 10: Final Draft (.fdx) import and export

**Files:**
- Create: `src/fdx/export.js`, `src/fdx/import.js`
- Modify:
  - `src/main/files.js`: add `'fdx'` to `IMPORT_EXTS` and `EXPORT_EXTS`.
  - `src/main.js`: the export-file filter name is Final Draft for fdx.
  - `src/ui/Library.jsx`: import dispatches on the extension.
  - `src/ui/EditorScreen.jsx`: Export menu item.
- Test: `src/fdx/__tests__/fdx.test.js` (jsdom), plus the existing `src/main/__tests__/files.test.js` (unchanged expectations)

**Interfaces:**
- Consumes: `parse`, `normalizeMeta`, `DEFAULT_META`, `applyType` (flow.js).
- Produces: `toFdx(meta, body) → xml string` and `fromFdx(xml, parser = new DOMParser()) → {meta, body}`, which throws `'Not a Final Draft (.fdx) file'` on bad input.

- [ ] **Step 1: Write failing tests**

`src/fdx/__tests__/fdx.test.js`:
```js
// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { parse } from '../../fountain/parse.js';
import { fromFdx } from '../import.js';
import { toFdx } from '../export.js';

const BODY = 'INT. LIGHTHOUSE - NIGHT\n\nRain **hammers** the glass.\n\nMARA\n(quietly)\nIt found us.\n\nBRICK\nScrew it.\n\nSTEEL ^\nScrew it.\n\nCUT TO:\n\n>THE END<\n';
const kinds = (b) => parse(b).map((e) => [e.type, e.dual ?? null]);

describe('fdx', () => {
  it('exports typed paragraphs, styles, dual dialogue and a title page', () => {
    const xml = toFdx({ title: 'The Long Night', author: 'J R' }, BODY);
    expect(xml.startsWith('<?xml')).toBe(true);
    expect(xml).toContain('<Paragraph Type="Scene Heading">');
    expect(xml).toContain('<Text Style="Bold">hammers</Text>');
    expect(xml).toContain('<DualDialogue>');
    expect(xml).toContain('<Paragraph Type="Action" Alignment="Center">');
    expect(xml).toContain('<TitlePage>');
    expect(xml).toContain('The Long Night');
  });
  it('round-trips element types, emphasis and title', () => {
    const { meta, body } = fromFdx(toFdx({ title: 'The Long Night' }, BODY));
    expect(meta.title).toBe('The Long Night');
    expect(kinds(body)).toEqual(kinds(BODY));
    expect(body).toContain('**hammers**');
    expect(body).toContain('>THE END<');
  });
  it('escapes XML and rejects non-FDX input', () => {
    expect(toFdx({}, 'Tom & Jerry <3')).toContain('Tom &amp; Jerry &lt;3');
    expect(() => fromFdx('<html></html>')).toThrow('Not a Final Draft (.fdx) file');
    expect(() => fromFdx('not xml at all <')).toThrow('Not a Final Draft (.fdx) file');
  });
});
```

- [ ] **Step 2: Run to verify failure.** Expected: FAIL.

- [ ] **Step 3: Implement**

`src/fdx/export.js`:
```js
// Fountain → Final Draft XML (FDX). Unprinted Fountain (notes, sections,
// synopses, boneyard, page breaks) is dropped.
import { normalizeMeta } from '../fountain/document.js';
import { parse } from '../fountain/parse.js';

const TYPE = {
  scene_heading: 'Scene Heading', action: 'Action', character: 'Character', parenthetical: 'Parenthetical',
  dialogue: 'Dialogue', transition: 'Transition', centered: 'Action', lyric: 'Action',
};
const UPPER = new Set(['scene_heading', 'character', 'transition']);
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };
const esc = (s) => s.replace(/[&<>"]/g, (c) => ESC[c]);

function runs(text) {
  const state = { b: false, i: false, u: false };
  const out = [];
  let buf = '';
  const flush = () => {
    if (!buf) return;
    const style = [state.b && 'Bold', state.i && 'Italic', state.u && 'Underline'].filter(Boolean).join('+');
    out.push(style ? `<Text Style="${style}">${esc(buf)}</Text>` : `<Text>${esc(buf)}</Text>`);
    buf = '';
  };
  let last = 0;
  for (const m of text.matchAll(/\\([*_])|\*\*\*|\*\*|\*|_/g)) {
    buf += text.slice(last, m.index);
    last = m.index + m[0].length;
    if (m[1]) { buf += m[1]; continue; }
    flush();
    if (m[0] === '***') { state.b = !state.b; state.i = !state.i; } else if (m[0] === '**') state.b = !state.b;
    else if (m[0] === '*') state.i = !state.i;
    else state.u = !state.u;
  }
  buf += text.slice(last);
  flush();
  return out.join('') || '<Text></Text>';
}

function paragraph(el, indent = '    ') {
  const text = UPPER.has(el.type) ? el.text.toUpperCase() : el.text;
  const align = el.type === 'centered' ? ' Alignment="Center"' : '';
  return `${indent}<Paragraph Type="${TYPE[el.type]}"${align}>${runs(text)}</Paragraph>`;
}

export function toFdx(meta, body) {
  const m = normalizeMeta(meta);
  const els = parse(body).filter((e) => TYPE[e.type]);
  const out = [];
  for (let k = 0; k < els.length; k++) {
    const el = els[k];
    if (el.type === 'character' && el.dual === 'left') {
      const block = [el];
      let j = k + 1;
      while (j < els.length && (els[j].type === 'dialogue' || els[j].type === 'parenthetical' || (els[j].type === 'character' && els[j].dual === 'right' && !block.some((b) => b.dual === 'right')))) {
        block.push(els[j]);
        j++;
      }
      if (block.some((b) => b.dual === 'right')) {
        out.push('    <Paragraph>', '      <DualDialogue>', ...block.map((b) => paragraph(b, '        ')), '      </DualDialogue>', '    </Paragraph>');
        k = j - 1;
        continue;
      }
    }
    out.push(paragraph(el));
  }
  const tp = [
    m.title && `      <Paragraph Alignment="Center">${runs(m.title)}</Paragraph>`,
    m.credit && `      <Paragraph Alignment="Center">${runs(m.credit)}</Paragraph>`,
    m.author && `      <Paragraph Alignment="Center">${runs(m.author)}</Paragraph>`,
    m.source && `      <Paragraph Alignment="Center">${runs(m.source)}</Paragraph>`,
    ...[m.draft_date, ...m.contact.split('\n')].filter(Boolean).map((l) => `      <Paragraph Alignment="Left">${runs(l)}</Paragraph>`),
  ].filter(Boolean);
  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>',
    '<FinalDraft DocumentType="Script" Template="No" Version="5">',
    '  <Content>',
    ...out,
    '  </Content>',
    '  <TitlePage>',
    '    <Content>',
    ...tp,
    '    </Content>',
    '  </TitlePage>',
    '</FinalDraft>',
    '',
  ].join('\n');
}
```

`src/fdx/import.js`:
```js
// Final Draft XML (FDX) → Fountain + title meta. Uses the renderer's DOMParser.
import { DEFAULT_META, normalizeMeta } from '../fountain/document.js';
import { applyType } from '../editor/flow.js';

const FROM = {
  'Scene Heading': 'scene_heading', Action: 'action', Character: 'character', Parenthetical: 'parenthetical',
  Dialogue: 'dialogue', Transition: 'transition', Shot: 'scene_heading', General: 'action',
};
const NOT_FDX = 'Not a Final Draft (.fdx) file';
const kids = (node, tag) => [...node.children].filter((c) => c.tagName === tag);

function styled(t) {
  const style = t.getAttribute('Style') ?? '';
  const raw = t.textContent.replace(/([*_])/g, '\\$1');
  if (!raw) return '';
  let s = raw;
  if (/Bold/.test(style) && /Italic/.test(style)) s = `***${s}***`;
  else if (/Bold/.test(style)) s = `**${s}**`;
  else if (/Italic/.test(style)) s = `*${s}*`;
  if (/Underline/.test(style)) s = `_${s}_`;
  return s;
}
const paraText = (p) => kids(p, 'Text').map(styled).join('');
const paraPlain = (p) => kids(p, 'Text').map((t) => t.textContent).join('').trim();

export function fromFdx(xml, parser = new DOMParser()) {
  let doc;
  try { doc = parser.parseFromString(String(xml), 'application/xml'); } catch { throw new Error(NOT_FDX); }
  const root = doc?.documentElement;
  if (!root || root.tagName !== 'FinalDraft' || doc.getElementsByTagName('parsererror').length) throw new Error(NOT_FDX);
  const content = kids(root, 'Content')[0];
  const out = [];

  const emit = (p, dualRight) => {
    const type = FROM[p.getAttribute('Type')] ?? 'action';
    const text = paraText(p).trim();
    if (!text) return;
    let line = type === 'action' && p.getAttribute('Alignment') === 'Center' ? `>${text}<` : applyType(text, type);
    if (type === 'character' && dualRight) line += ' ^';
    if ((type === 'dialogue' || type === 'parenthetical') && out.length) out.push(line);
    else { if (out.length) out.push(''); out.push(line); }
  };

  for (const p of content ? kids(content, 'Paragraph') : []) {
    const dual = kids(p, 'DualDialogue')[0];
    if (!dual) { emit(p, false); continue; }
    let cues = 0;
    for (const q of kids(dual, 'Paragraph')) {
      const isCue = q.getAttribute('Type') === 'Character';
      if (isCue) cues++;
      emit(q, isCue && cues === 2);
    }
  }

  const meta = { ...DEFAULT_META };
  const tp = kids(root, 'TitlePage')[0];
  if (tp) {
    const lines = [...tp.getElementsByTagName('Paragraph')].map(paraPlain).filter(Boolean);
    if (lines[0]) meta.title = lines[0];
  }
  return { meta: normalizeMeta(meta), body: `${out.join('\n')}\n` };
}
```
`applyType` on dialogue returns the trimmed text; on character it uppercases; on a transition it adds `>` unless the text ends in `TO:`; on a scene heading it adds `.` when there's no INT./EXT. prefix; on a parenthetical it re-wraps the parens.

`src/main/files.js`: set `IMPORT_EXTS = ['fountain', 'spmd', 'txt', 'fdx']` and `EXPORT_EXTS = ['fountain', 'txt', 'fdx']`. In `src/main.js` `exportFile`, the filter name becomes `{ fountain: 'Fountain', fdx: 'Final Draft' }[ext] ?? 'Text'`.

`src/ui/Library.jsx`: add `import { fromFdx } from '../fdx/import.js';`, and in `importFountain` replace `const parsed = fromFountain(r.content);` with:
```js
      const parsed = /\.fdx$/i.test(r.name) ? fromFdx(r.content) : fromFountain(r.content);
```
Rename the button label to "Import script" (keep the `FileUp` icon).

`src/ui/EditorScreen.jsx`: add `import { toFdx } from '../fdx/export.js';` and an export function beside `exportFountain`:
```jsx
  async function exportFdx() {
    setMenu(false);
    try {
      const content = toFdx(metaRef.current, viewRef.current.state.doc.toString());
      const r = await plugin.ipc.invoke('export-file', { defaultName: slug, ext: 'fdx', content });
      if (r?.path) notify(`Final Draft file saved to ${r.path}`);
    } catch (e) {
      notify(`Export failed: ${e.message}`, 'error');
    }
  }
```
Add a menu item after Fountain: `<button type="button" onClick={exportFdx}><FileText size={12} /> Final Draft (.fdx)</button>`.

- [ ] **Step 4: Run the full suite and build.** Expected: PASS.
- [ ] **Step 5: Commit** as "feat(script-writer): Final Draft (.fdx) import and export".

---

### Task 11: Release 0.2.0 (README, build, Electron smoke)

**Files:**
- Modify: `manifest.json` (`"version": "0.2.0"`; description adds "AI co-writer grounded in your vault, one-click Polish"), `README.md`
- Commit: `dist/**`

- [ ] **Step 1: README**

Add these sections to `plugins/script-writer/README.md`, after "Writing":
```markdown
## Formatting

Use the formatting bar above the page:
- The **element dropdown** shows the current line's element and changes it (the same as Tab or ⌘1–7).
- **B / I / U** wrap the selection in bold, italic or underline (⌘B / ⌘I / ⌘U). They unwrap it if it's already wrapped.
- **+ Scene** starts a new scene after the one you're in.

You can also type Fountain directly:
- `**bold**`, `*italic*`, `_underline_`
- `>THE END<` for centered text
- `===` for a page break
- `[[note]]` for a note that doesn't print

## AI co-writer (⌘K)

Everything uses the AI provider you've set up in Poltergeist.

- **Ask.** It searches your vault, starting with this script's project folder, then the whole context. It answers with clickable `[n]` citations to your notes. Each script keeps its own conversation.
- **Actions.** Continue scene, Rewrite (tighter, funnier, darker, more subtext, or your own direction), Punch up dialogue, Scene from beat, and Continuity check. They work on the selection, or on the scene at the cursor. Suggestions appear in the script as an Accept / Insert / Reject block, and editing that text cancels the suggestion.
- **Polish.** Polishes the whole script, scene by scene, with Formatting, Language, Tighten prose and Punch up dialogue passes. You review every change in one view and keep or drop each one. Apply is a single ⌘Z. A scene the AI mangled is kept as it was and flagged.

## Final Draft

Import `.fdx` files from the Library. Export `.fdx` from the Export menu.
```

- [ ] **Step 2: Version, rebuild, full suite, and commit `dist/`**

```bash
cd /Users/jannik/development/nikrich/ghost-brain/.claude/worktrees/script-writer-ai/plugins/script-writer && npx vitest run && rm -rf dist && npm run build && cd ../.. && git add plugins/script-writer && git commit -m "feat(script-writer): v0.2.0 — AI co-writer, Polish, formatting bar, FDX

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 3: Electron smoke (the controller dispatches this)**

The controller dispatches it with the slice 1 harness in the session scratchpad (`sw-smoke/`), extended with fake `/v1/search` and `/v1/llm/run` routes. It checks, with real key events:
- ⌘K opens the AI panel. An Ask shows the answer with a citation, and the citation opens the source.
- Run "Punch up dialogue": the proposal widget renders, and Accept changes the doc; ⌘Z undoes it in one step.
- The format bar: Bold wraps the selection, the element dropdown retypes the line, and + Scene inserts `INT. `.
- Polish with the fake provider: the review lists the changes, one gets unticked, Apply lands exactly the kept ones, and ⌘Z restores the original.
- An FDX export round-trips.

Then one real `/v1/llm/run` call through the live sidecar with `budgetUsd: 0.05` on a 3-line polish, to prove the provider integration.

- [ ] **Step 4: Ship.** Push the branch, open a PR against `main` and wait for CI (backend, desktop). Merge with a merge commit. The marketplace entry tracks `main`, so the publish workflow picks up 0.2.0. Confirm with `curl -s https://market.getpoltergeist.com/registry.json` showing `script-writer 0.2.0`. If it doesn't update within 15 minutes, dispatch the registry's `publish.yml` with `gh workflow run publish.yml -R nikrich/poltergeist-plugins`.
