# A4 Focus Mode + Read-Aloud Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add focus mode (⌘. on macOS, Ctrl+. on Windows) that hides everything except the page being edited, and add read-aloud that speaks a note sentence by sentence through the OS voices, offline, highlights the sentence being read, and has a voice and speed picker in Settings › editor.

**Architecture:** Focus mode is a persisted `focusMode` settings flag. It only takes effect while an editor "surface" is mounted (the jots editor or the note viewer). App, JotsScreen and NoteView hide their chrome when it is active, and `RichMarkdownEditor` gets one `focus` prop that hides its formatting toolbar and centres the page at 72ch. Read-aloud runs entirely in the renderer on the Web Speech API (`window.speechSynthesis`). Pure modules handle text extraction from the ProseMirror doc, a playback controller (one utterance per sentence), voice selection and a decoration-only highlight plugin. A `ReadAloudControls` component in the editor's footer strip ties them together. No schema node is added, so the markdown on disk is untouched.

**Tech Stack:** Electron 32 (Chromium speech synthesis), React 18, Tiptap 2.27.2 (`@tiptap/pm/state`, `@tiptap/pm/view`), zustand 5, zod 4, `Intl.Segmenter` (ES2022, already in `tsconfig.web.json` lib), Vitest 2 + jsdom + Testing Library 16. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-10-09-confluence-editor-design.md`, section "Focus mode and read-aloud", slice **A4**. A1–A3, A5, A6 and spec B are out of scope. Already on main and only read here: B1 `GuardedNoteEditor` (in `screens/jots.tsx` and `components/NoteView.tsx`), A2 `BacklinksPanel`, and the Electron navigation guard.

## Global Constraints

- Read-aloud uses **OS voices only, offline, never a cloud TTS** (spec decision 3, approved by the user). Only voices with `localService === true` are listed or chosen.
- No new npm dependencies. No new IPC channel, preload API or main-process code. The only main-side change is three settings keys (schema and defaults).
- Focus mode: "a `focus` flag in `stores/settings` (persisted). It hides the sidebar nav, JotTree, the assist panel and the toolbar, and centres the page at 72ch. Esc or ⌘. exits." On Windows the shortcut is Ctrl+. .
- Read-aloud: "A '▶ Read' button reads the selection, or the document from the cursor. The current sentence is highlighted with a decoration. The voice and rate pickers are in Settings › Editor. The default voice matches the note's dominant language, so an Afrikaans note uses an Afrikaans voice when one is installed and falls back to the default otherwise."
- "Speech synthesis unavailable: the Read button is hidden."
- Files on disk stay plain markdown. A4 adds **no** node or mark to `buildEditorExtensions()`. The highlight is a runtime-registered decoration plugin that never changes the document and never triggers an autosave.
- A1 is editing the editor extensions and toolbar in parallel. A4 does **not** touch `lib/editor/extensions.ts`, `EditorToolbar.tsx`, `slash.ts` or `markdown-roundtrip.test.ts`. Edits to `RichMarkdownEditor.tsx` and `styles.css` stay small and additive: one prop, one attribute, one toolbar condition, one footer line, and appended CSS.
- Run every command from `desktop/`. Typecheck is `npm run typecheck` (`tsc -b`), **not** `tsc --noEmit`. Tests: `npx vitest run <file>`. Lint: `npx eslint --max-warnings 0 <files>` (full gate: `npm run lint`).
- Windows release builds rerun the desktop tests, so tests must not assert POSIX-only paths or line endings.
- UI copy is lower-case, matching the app (`copy formatted`, `rich`, `src`).
- No real people's or employer names in code, fixtures or copy.

## Review Focus

1. **Late speech events after pause, stop or a note switch.** Chromium fires `end`, or `error` with `interrupted`/`canceled`, for a cancelled utterance *asynchronously*. Those events must never advance, restart or double-speak. Pinned in Task 7 (`ignores a late end/error from a paused or stopped utterance`) and Task 9 (`unmounting (note switch) stops speech and ignores the late end event`).
2. **Editing the note while it is being read.** The highlight and the queued sentence ranges must follow the text, never throw on out-of-range positions, and never cause an autosave. Pinned in Task 6 (`maps the highlight through edits`, `clamps out-of-range ranges`, `never changes the doc, fires no update and adds no undo step`) and Task 9 (`the highlight never triggers an autosave and follows edits`).
3. **Esc precedence.** Esc in an open slash or suggestion menu closes the menu and does not leave focus mode. In the note viewer in focus mode, the first Esc leaves focus and the second closes the viewer. Pinned in Task 2 (`Esc already handled by the editor does not leave focus`) and Task 4 (`in focus mode Esc does not close the viewer`, `without focus mode Esc still closes the viewer`).
4. **A persisted `focusMode: true` with no editor on screen** (an app restart onto Today, Settings, or deleting the last jot). The sidebar must stay visible, and ⌘. does nothing there. Pinned in Task 2 (`is inactive without an editor surface`, `⌘. does nothing with no editor on screen`) and Task 3 (`focus mode hides the sidebar and status bar only while an editor surface is up`).
5. **Voices that are missing or late.** The chosen voice may have been uninstalled, voices may arrive after mount (`voiceschanged`), no Afrikaans voice may be installed, or a network voice may be present. Each case falls back to auto or the OS default and never selects a non-local voice. Pinned in Task 8 (`pickVoice` cases, `drops network voices`, `picks up voices that load late`) and Task 10 (`says when the chosen voice is no longer installed`).

## Decisions taken where the spec leaves room

- **TTS mechanism: the Web Speech API in the renderer.** It is not macOS `say` or Windows SAPI driven from main. Chromium keeps speech synthesis in the **browser process**: `TtsController` uses the platform engine, which is AVSpeechSynthesizer/NSSpeechSynthesizer on macOS and SAPI on Windows. The sandboxed renderer only sends Mojo messages to it, so `sandbox: true` + `contextIsolation: true` (`desktop/src/main/index.ts:135-139`) don't block it, and no preload bridge is needed. It speaks through the same OS voices as `say`/SAPI, and it brings voice enumeration, rate, cancel and per-utterance `end`/`error` events. A main-process route would need new IPC, spawning `say` or PowerShell `System.Speech` (slow start, argument-escaping risk, no sentence events without extra work), plus separate voice listing per OS. Electron, unlike branded Chrome, ships no Google network voices. The `localService` filter still guarantees offline use if a future engine adds some. On Linux, Chromium needs speech-dispatcher. When it's missing, the first utterance fails with `synthesis-unavailable`, and the controller stops and toasts. Linux is not a primary target.
- **One utterance per sentence.** This avoids Chromium cutting off long utterances. Highlighting comes from "which utterance is speaking", not from `boundary` events, which some voices don't emit, so it costs nothing extra.
- **Pause is "cancel and remember the sentence"; resume re-speaks that sentence from its start.** `speechSynthesis.pause()` behaves differently per platform. Restarting a sentence is deterministic and testable.
- **What is read.** Text comes from the ProseMirror document, never from markdown source, so markdown syntax is never spoken. Every textblock (paragraph, heading, list item, table cell, blockquote/callout body) is split into sentences with `Intl.Segmenter`.
  - Skipped: nodes whose spec has `code: true` (code blocks, including A1's mermaid fences), and leaf and atom blocks (images, TOC, rules).
  - Frontmatter is never in the editor: `Note.body` excludes it.
  - Inline atoms (hard break, A1's status lozenge) are silent and count as a space.
  - Spoken-text clean-up: `[[path|Alias]]` → `Alias` (with a leading `@` dropped), `[[a/b/note]]` → `note`, `#project/alpha` → `project alpha`, bare URLs → `link`. Sentences with no letter or digit are skipped.
- **Where reading starts.** With a non-empty selection, only the selected text is read (partial sentences clipped). With an empty selection, reading starts at the sentence containing the cursor. If the cursor is past the last sentence, it starts from the top. A note with nothing readable toasts `nothing to read here`.
- **Voice choice.** The setting `readAloudVoice` is a `voiceURI`, or `''` for **auto**. Auto detects the note's dominant language (Afrikaans vs English, stop-word count) and picks an installed voice for it, preferring the OS default voice among matches. Otherwise it uses the OS default voice. An explicit voice always wins. If that voice is no longer installed, auto is used and Settings says so.
- **Rate** is `readAloudRate`, from 0.5 to 2 in steps of 0.1, default 1. Voice and rate are read when reading starts.
- **Read-aloud shortcut: ⌘⇧L / Ctrl+Shift+L ("listen")** toggles read → pause → resume while the editor has focus. I checked every binding in the app: ⌘⇧C copy-formatted (`RichMarkdownEditor`), ⌘K (Today), ⌘, (menu), ⌥J (global jot overlay), the ⌘⇧K/C/R/S/V/G labels in `lib/shortcuts.ts`, the Tiptap StarterKit/TaskList keymaps (Mod-B/I/E/Z/Y, Mod-Shift-S/7/8/9, Mod-Alt-0…6/C, Mod-Enter), and A5's planned ⌘J. Neither ⌘. nor ⌘⇧L collides with any of them. Esc does **not** stop reading, because Esc already closes menus, the viewer and focus mode. The stop button stops reading, and so do switching notes and switching to source mode.
- **Focus mode only applies while an editor is on screen.** That means the jots screen with a jot open, or the note viewer. The flag is persisted as the spec says, but on any other screen it has no effect and ⌘. is ignored.
  - In focus mode, the jots screen hides the TopBar, search, JotTree, backlinks, footer and assist panel. App hides the sidebar and status bar. The note viewer becomes full-width and hides its header and backlinks.
  - A thin `FocusBar` replaces the top bar. It is a window-drag strip that clears the macOS traffic lights and has one `exit focus · esc` button.
  - The editor's own bottom strip (`copy formatted`, read controls, `rich`/`src`) stays, so read-aloud works in focus mode.
  - Mouse users get a `focus mode` button in the jots top bar and the note-viewer header.
- **⌘. is handled by a renderer `keydown` listener, not a menu accelerator.** VS Code (also Electron) binds ⌘. in the renderer on macOS, so the key reaches the page. One listener in App avoids the double-fire that a menu accelerator plus page handler would cause, and needs no IPC.
- Read controls show only in **rich** mode. Source mode has no ProseMirror document to highlight.

---

## File Structure

Create (all under `desktop/src/renderer/` unless noted):

| File | Responsibility |
|---|---|
| `lib/editor-shortcuts.ts` | The two A4 shortcuts: matcher and display label per platform |
| `lib/focus-mode.ts` | Focus surfaces store, `useFocusSurface`, `useFocusActive`, `focusActiveNow`, `setFocusMode`, `useFocusModeShortcuts` |
| `components/FocusBar.tsx` | Drag strip + "exit focus" button shown instead of top bars |
| `lib/read-aloud/segments.ts` | Doc → speakable sentence segments with doc ranges; `speakable`, `startIndexFor` |
| `lib/read-aloud/language.ts` | `detectLanguage(text)`: `'af' \| 'en' \| null` |
| `lib/read-aloud/highlight.ts` | Decoration-only ProseMirror plugin; attach/detach/set helpers |
| `lib/read-aloud/controller.ts` | `ReadAloudController`: per-sentence playback, pause/resume/stop, stale-event guard |
| `lib/read-aloud/voices.ts` | Support check, offline voice list hook, `pickVoice`, `makeUtterance`, `previewVoice` |
| `components/ReadAloudControls.tsx` | Read/pause/resume/stop buttons, ⌘⇧L, wiring controller ↔ editor |
| `__tests__/helpers/fake-speech.ts` | Fake `speechSynthesis` + utterance for jsdom tests |
| `__tests__/editor-shortcuts.test.ts`, `focus-mode.test.tsx`, `read-aloud-segments.test.ts`, `read-aloud-highlight.test.ts`, `read-aloud-controller.test.ts`, `read-aloud-voices.test.tsx`, `ReadAloudControls.test.tsx`, `EditorSettings.test.tsx` | Tests per unit |
| `desktop/src/main/__tests__/settings-schema.test.ts` | Schema validation for the new keys |

Modify:

| File | Change |
|---|---|
| `desktop/src/shared/types.ts`, `desktop/src/shared/settings-schema.ts`, `desktop/src/main/settings.ts`, `desktop/src/main/demo/fixtures.ts`, `stores/settings.ts`, `test/setup.ts` | Three settings keys + defaults |
| `desktop/src/main/settings.test.ts` | Defaults test |
| `App.tsx` | Hide Sidebar + StatusBar in focus; mount the focus shortcut hook |
| `components/RichMarkdownEditor.tsx` | `focus` prop (hide toolbar, `data-focus`), mount `ReadAloudControls` in the footer |
| `styles.css` (append) | Focus centring, sentence highlight |
| `screens/jots.tsx` | Register surface, hide chrome in focus, focus button |
| `components/NoteView.tsx` | Register surface, full-width + FocusBar in focus, Esc precedence, focus button |
| `screens/settings.tsx` | New `editor` section: `EditorSettings` |
| `__tests__/App.test.tsx`, `RichMarkdownEditor.test.tsx`, `jots.test.tsx`, `NoteView.test.tsx` | Focus tests |

---

### Task 1: Editor settings keys

**Files:**
- Modify: `desktop/src/shared/types.ts` (interface `Settings`)
- Modify: `desktop/src/shared/settings-schema.ts`
- Modify: `desktop/src/main/settings.ts` (`DEFAULT_SETTINGS`)
- Modify: `desktop/src/main/demo/fixtures.ts` (`DEMO_SETTINGS`)
- Modify: `desktop/src/renderer/stores/settings.ts` (placeholder defaults)
- Modify: `desktop/src/renderer/test/setup.ts` (`defaultSettings`)
- Modify: `desktop/src/main/settings.test.ts`
- Create: `desktop/src/main/__tests__/settings-schema.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings.focusMode: boolean` (default `false`), `Settings.readAloudVoice: string` (a `voiceURI`; `''` = auto; default `''`), `Settings.readAloudRate: number` (0.5–2; default `1`). They are written through the existing `useSettings.getState().set(key, value)`, which validates against `settingsSchema.shape[key]` in main.

- [ ] **Step 1: Write the failing tests**

Append to the `describe('settings store', …)` block in `desktop/src/main/settings.test.ts`:

```ts
  it('defaults the editor keys: focus off, auto voice, normal rate', async () => {
    const { getAll } = await import('./settings');
    const s = getAll();
    expect(s.focusMode).toBe(false);
    expect(s.readAloudVoice).toBe('');
    expect(s.readAloudRate).toBe(1);
  });

  it('an older config.json without the editor keys gets their defaults', async () => {
    const { writeFileSync } = await import('node:fs');
    writeFileSync(join(workDir, 'config.json'), JSON.stringify({ version: 1, theme: 'light' }));
    const { getAll } = await import('./settings');
    expect(getAll().focusMode).toBe(false);
    expect(getAll().readAloudRate).toBe(1);
  });
```

Create `desktop/src/main/__tests__/settings-schema.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { settingsSchema } from '../../shared/settings-schema';

describe('settings schema — editor keys (A4)', () => {
  it('focusMode is a boolean', () => {
    expect(settingsSchema.shape.focusMode.safeParse(true).success).toBe(true);
    expect(settingsSchema.shape.focusMode.safeParse('yes').success).toBe(false);
  });

  it('readAloudVoice accepts any voice id, including empty for auto', () => {
    expect(settingsSchema.shape.readAloudVoice.safeParse('').success).toBe(true);
    expect(
      settingsSchema.shape.readAloudVoice.safeParse('com.apple.voice.compact.en-US.Samantha')
        .success,
    ).toBe(true);
    expect(settingsSchema.shape.readAloudVoice.safeParse('x'.repeat(513)).success).toBe(false);
    expect(settingsSchema.shape.readAloudVoice.safeParse(3).success).toBe(false);
  });

  it('readAloudRate is a number from 0.5 to 2', () => {
    expect(settingsSchema.shape.readAloudRate.safeParse(0.5).success).toBe(true);
    expect(settingsSchema.shape.readAloudRate.safeParse(2).success).toBe(true);
    expect(settingsSchema.shape.readAloudRate.safeParse(0.4).success).toBe(false);
    expect(settingsSchema.shape.readAloudRate.safeParse(2.1).success).toBe(false);
    expect(settingsSchema.shape.readAloudRate.safeParse('1').success).toBe(false);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/main/settings.test.ts src/main/__tests__/settings-schema.test.ts`
Expected: FAIL. `s.focusMode` is `undefined`, and `settingsSchema.shape.focusMode` is undefined (TypeError).

- [ ] **Step 3: Add the keys everywhere**

`desktop/src/shared/types.ts`: in `interface Settings`, after `onboardingComplete: boolean;`, add:

```ts
  /** Focus mode (⌘. / Ctrl+.): hide everything but the page being edited. */
  focusMode: boolean;
  /** voiceURI of the read-aloud voice; '' = auto (match the note's language). */
  readAloudVoice: string;
  /** Read-aloud speaking rate, 0.5–2 (1 = normal). */
  readAloudRate: number;
```

`desktop/src/shared/settings-schema.ts`: after `onboardingComplete: z.boolean(),`, add:

```ts
  // Editor (A4): focus mode + read-aloud. Voice '' = auto by note language.
  focusMode: z.boolean(),
  readAloudVoice: z.string().max(512),
  readAloudRate: z.number().min(0.5).max(2),
```

`desktop/src/main/settings.ts`: in `DEFAULT_SETTINGS`, after `onboardingComplete: false,`, add:

```ts
  focusMode: false,
  readAloudVoice: '',
  readAloudRate: 1,
```

`desktop/src/renderer/stores/settings.ts`: in the store's placeholder defaults, after `onboardingComplete: false,`, add the same three lines.

`desktop/src/renderer/test/setup.ts`: in `defaultSettings`, after `onboardingComplete: false,`, add the same three lines.

`desktop/src/main/demo/fixtures.ts`: in `DEMO_SETTINGS`, after `schedulerEnabled: true,`, add:

```ts
  focusMode: false,
  readAloudVoice: '',
  readAloudRate: 1,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/main/settings.test.ts src/main/__tests__/settings-schema.test.ts`
Expected: PASS.

- [ ] **Step 5: Typecheck + lint**

Run: `npm run typecheck && npx eslint --max-warnings 0 src/shared/types.ts src/shared/settings-schema.ts src/main/settings.ts src/main/demo/fixtures.ts src/renderer/stores/settings.ts src/renderer/test/setup.ts src/main/settings.test.ts src/main/__tests__/settings-schema.test.ts`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/shared/types.ts src/shared/settings-schema.ts src/main/settings.ts src/main/demo/fixtures.ts src/renderer/stores/settings.ts src/renderer/test/setup.ts src/main/settings.test.ts src/main/__tests__/settings-schema.test.ts
git commit -m "feat(settings): focusMode, readAloudVoice and readAloudRate keys"
```

---

### Task 2: Editor shortcuts and focus-mode core

**Files:**
- Create: `desktop/src/renderer/lib/editor-shortcuts.ts`
- Create: `desktop/src/renderer/lib/focus-mode.ts`
- Create: `desktop/src/renderer/components/FocusBar.tsx`
- Create: `desktop/src/renderer/__tests__/editor-shortcuts.test.ts`
- Create: `desktop/src/renderer/__tests__/focus-mode.test.tsx`

**Interfaces:**
- Consumes: `Settings.focusMode` and `useSettings().set` (Task 1); `isMac` from `lib/platform.ts`; `toast` from `stores/toast.ts`.
- Produces:
  - `lib/editor-shortcuts.ts`: `type EditorShortcut = 'focus' | 'readAloud'`, `type KeyLike = Pick<KeyboardEvent, 'key' | 'metaKey' | 'ctrlKey' | 'shiftKey' | 'altKey'>`, `matchesShortcut(e: KeyLike, which: EditorShortcut, mac: boolean): boolean`, `shortcutLabel(which: EditorShortcut, mac?: boolean): string` (`'⌘ .'`, `'Ctrl .'`, `'⌘ ⇧ L'`, `'Ctrl ⇧ L'`).
  - `lib/focus-mode.ts`: `useFocusSurfaces` (zustand: `{ count: number; register(): () => void }`), `useFocusSurface(enabled: boolean): void`, `useFocusActive(): boolean`, `focusActiveNow(): boolean`, `setFocusMode(on: boolean): Promise<void>`, `useFocusModeShortcuts(): void`.
  - `components/FocusBar.tsx`: `FocusBar()` renders `data-testid="focus-bar"` with a button `aria-label="exit focus mode"`.

- [ ] **Step 1: Write the failing tests**

`desktop/src/renderer/__tests__/editor-shortcuts.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { matchesShortcut, shortcutLabel, type KeyLike } from '../lib/editor-shortcuts';

const k = (key: string, mods: Partial<KeyLike> = {}): KeyLike => ({
  key,
  metaKey: false,
  ctrlKey: false,
  shiftKey: false,
  altKey: false,
  ...mods,
});

describe('editor shortcuts', () => {
  it('focus is ⌘. on macOS and Ctrl+. elsewhere', () => {
    expect(matchesShortcut(k('.', { metaKey: true }), 'focus', true)).toBe(true);
    expect(matchesShortcut(k('.', { ctrlKey: true }), 'focus', true)).toBe(false);
    expect(matchesShortcut(k('.', { ctrlKey: true }), 'focus', false)).toBe(true);
    expect(matchesShortcut(k('.', { metaKey: true }), 'focus', false)).toBe(false);
  });

  it('focus ignores shifted and alt variants', () => {
    expect(matchesShortcut(k('>', { metaKey: true, shiftKey: true }), 'focus', true)).toBe(false);
    expect(matchesShortcut(k('.', { metaKey: true, shiftKey: true }), 'focus', true)).toBe(false);
    expect(matchesShortcut(k('.', { metaKey: true, altKey: true }), 'focus', true)).toBe(false);
    expect(matchesShortcut(k('.'), 'focus', true)).toBe(false);
  });

  it('read aloud is ⌘⇧L / Ctrl+Shift+L in either letter case', () => {
    expect(matchesShortcut(k('L', { metaKey: true, shiftKey: true }), 'readAloud', true)).toBe(true);
    expect(matchesShortcut(k('l', { metaKey: true, shiftKey: true }), 'readAloud', true)).toBe(true);
    expect(matchesShortcut(k('L', { ctrlKey: true, shiftKey: true }), 'readAloud', false)).toBe(true);
    expect(matchesShortcut(k('l', { metaKey: true }), 'readAloud', true)).toBe(false);
    expect(matchesShortcut(k('L', { ctrlKey: true, shiftKey: true }), 'readAloud', true)).toBe(false);
  });

  it('labels per platform', () => {
    expect(shortcutLabel('focus', true)).toBe('⌘ .');
    expect(shortcutLabel('focus', false)).toBe('Ctrl .');
    expect(shortcutLabel('readAloud', true)).toBe('⌘ ⇧ L');
    expect(shortcutLabel('readAloud', false)).toBe('Ctrl ⇧ L');
  });
});
```

`desktop/src/renderer/__tests__/focus-mode.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import {
  focusActiveNow,
  useFocusActive,
  useFocusModeShortcuts,
  useFocusSurface,
  useFocusSurfaces,
} from '../lib/focus-mode';
import { FocusBar } from '../components/FocusBar';
import { useSettings } from '../stores/settings';

function Harness({ surface }: { surface: boolean }) {
  useFocusSurface(surface);
  useFocusModeShortcuts();
  const active = useFocusActive();
  return <div data-testid="state">{active ? 'on' : 'off'}</div>;
}

beforeEach(() => {
  useSettings.setState({ focusMode: false });
  useFocusSurfaces.setState({ count: 0 });
});

afterEach(() => {
  useSettings.setState({ focusMode: false });
  useFocusSurfaces.setState({ count: 0 });
});

describe('focus mode core', () => {
  it('is inactive without an editor surface, even when the flag is on', () => {
    useSettings.setState({ focusMode: true });
    render(<Harness surface={false} />);
    expect(screen.getByTestId('state')).toHaveTextContent('off');
    expect(focusActiveNow()).toBe(false);
  });

  it('is active when the flag is on and a surface is mounted', () => {
    useSettings.setState({ focusMode: true });
    render(<Harness surface />);
    expect(screen.getByTestId('state')).toHaveTextContent('on');
    expect(focusActiveNow()).toBe(true);
  });

  it('unmounting the surface deactivates it; release is idempotent', () => {
    const release = useFocusSurfaces.getState().register();
    expect(useFocusSurfaces.getState().count).toBe(1);
    release();
    release();
    expect(useFocusSurfaces.getState().count).toBe(0);
  });

  it('⌘. toggles focus while an editor is on screen', async () => {
    render(<Harness surface />);
    fireEvent.keyDown(window, { key: '.', metaKey: true });
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('on'));
    fireEvent.keyDown(window, { key: '.', metaKey: true });
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('off'));
  });

  it('⌘. does nothing with no editor on screen', async () => {
    render(<Harness surface={false} />);
    fireEvent.keyDown(window, { key: '.', metaKey: true });
    await act(async () => {});
    expect(useSettings.getState().focusMode).toBe(false);
  });

  it('Esc leaves focus mode', async () => {
    useSettings.setState({ focusMode: true });
    render(<Harness surface />);
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(useSettings.getState().focusMode).toBe(false));
  });

  it('Esc already handled by the editor does not leave focus', async () => {
    useSettings.setState({ focusMode: true });
    render(<Harness surface />);
    const menu = document.createElement('div');
    document.body.append(menu);
    // ProseMirror calls preventDefault when a suggestion/slash menu consumes Esc.
    menu.addEventListener('keydown', (e) => e.preventDefault());
    fireEvent.keyDown(menu, { key: 'Escape' });
    await act(async () => {});
    expect(useSettings.getState().focusMode).toBe(true);
    menu.remove();
  });

  it('FocusBar exit button turns focus off', async () => {
    useSettings.setState({ focusMode: true });
    render(<FocusBar />);
    fireEvent.click(screen.getByRole('button', { name: 'exit focus mode' }));
    await waitFor(() => expect(useSettings.getState().focusMode).toBe(false));
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/renderer/__tests__/editor-shortcuts.test.ts src/renderer/__tests__/focus-mode.test.tsx`
Expected: FAIL with "Failed to resolve import '../lib/editor-shortcuts'" (and `../lib/focus-mode`).

- [ ] **Step 3: Write the implementation**

`desktop/src/renderer/lib/editor-shortcuts.ts`:

```ts
import { isMac } from './platform';

/** Editor-scope shortcuts added by A4 (focus mode, read-aloud).
 *
 * Collision check (2026-10-09): ⌘⇧C copy-formatted, ⌘K Today search, ⌘,
 * settings, ⌥J jot overlay, the ⌘⇧K/C/R/S/V/G labels in lib/shortcuts.ts,
 * Tiptap StarterKit/TaskList keymaps (Mod-B/I/E/Z/Y, Mod-Shift-S/7/8/9,
 * Mod-Alt-0…6/C, Mod-Enter) and A5's planned ⌘J. Neither binding below
 * collides with any of them. */
export type EditorShortcut = 'focus' | 'readAloud';

export type KeyLike = Pick<KeyboardEvent, 'key' | 'metaKey' | 'ctrlKey' | 'shiftKey' | 'altKey'>;

const SPEC: Record<EditorShortcut, { key: string; shift: boolean; glyph: string }> = {
  focus: { key: '.', shift: false, glyph: '.' },
  readAloud: { key: 'l', shift: true, glyph: 'L' },
};

/** Mod = ⌘ on macOS, Ctrl elsewhere; the other modifier must be up so
 * Ctrl+. on a Mac (or Win+. on Windows) never triggers it. */
export function matchesShortcut(e: KeyLike, which: EditorShortcut, mac: boolean): boolean {
  const s = SPEC[which];
  if (e.key.toLowerCase() !== s.key || e.shiftKey !== s.shift || e.altKey) return false;
  return mac ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
}

export function shortcutLabel(which: EditorShortcut, mac = isMac): string {
  const s = SPEC[which];
  return [mac ? '⌘' : 'Ctrl', ...(s.shift ? ['⇧'] : []), s.glyph].join(' ');
}
```

`desktop/src/renderer/lib/focus-mode.ts`:

```ts
import { useEffect } from 'react';
import { create } from 'zustand';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { matchesShortcut } from './editor-shortcuts';
import { isMac } from './platform';

/** Number of mounted views that show an editable page (the jots editor, the
 * note viewer). Focus mode only takes effect while at least one is up, so a
 * persisted `focusMode: true` never hides the sidebar on Today or Settings. */
interface FocusSurfaceState {
  count: number;
  register: () => () => void;
}

export const useFocusSurfaces = create<FocusSurfaceState>((set) => ({
  count: 0,
  register: () => {
    set((s) => ({ count: s.count + 1 }));
    let released = false;
    return () => {
      if (released) return;
      released = true;
      set((s) => ({ count: Math.max(0, s.count - 1) }));
    };
  },
}));

/** Register the calling view as an editor surface while `enabled`. */
export function useFocusSurface(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    return useFocusSurfaces.getState().register();
  }, [enabled]);
}

export function useFocusActive(): boolean {
  const on = useSettings((s) => s.focusMode);
  const surfaces = useFocusSurfaces((s) => s.count);
  return on && surfaces > 0;
}

/** Non-hook read for event handlers. */
export function focusActiveNow(): boolean {
  return useSettings.getState().focusMode && useFocusSurfaces.getState().count > 0;
}

export async function setFocusMode(on: boolean): Promise<void> {
  const r = await useSettings.getState().set('focusMode', on);
  if (!r.ok) toast.error(r.error);
}

/** App-level keyboard handling: ⌘. / Ctrl+. toggles (only with an editor on
 * screen); Esc leaves focus mode unless something (a ProseMirror menu)
 * already consumed it. Marks the Esc as handled so the note viewer, which
 * also listens for Esc, does not close in the same keystroke. */
export function useFocusModeShortcuts(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (matchesShortcut(e, 'focus', isMac)) {
        if (useFocusSurfaces.getState().count === 0) return;
        e.preventDefault();
        void setFocusMode(!useSettings.getState().focusMode);
        return;
      }
      if (e.key === 'Escape' && !e.defaultPrevented && focusActiveNow()) {
        e.preventDefault();
        void setFocusMode(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
```

`desktop/src/renderer/components/FocusBar.tsx`:

```tsx
import { setFocusMode } from '../lib/focus-mode';
import { isMac } from '../lib/platform';
import { Lucide } from './Lucide';

/** Replaces the top bar / note header while focus mode is on: a thin
 * window-drag strip (left padding clears the macOS traffic lights) with one
 * way out for mouse users. */
export function FocusBar() {
  return (
    <div
      data-testid="focus-bar"
      className="flex h-9 flex-shrink-0 items-center justify-end pr-3"
      style={{ WebkitAppRegion: 'drag', paddingLeft: isMac ? 80 : 12 }}
    >
      <button
        type="button"
        aria-label="exit focus mode"
        onClick={() => void setFocusMode(false)}
        className="flex items-center gap-[6px] rounded-sm px-2 py-[3px] font-mono text-10 text-ink-3 opacity-60 hover:bg-vellum hover:text-ink-1 hover:opacity-100"
        style={{ WebkitAppRegion: 'no-drag' }}
      >
        <Lucide name="minimize-2" size={12} /> exit focus · esc
      </button>
    </div>
  );
}
```

(`WebkitAppRegion` is already typed by `src/shared/csstype.d.ts`; `Sidebar.tsx` uses it the same way.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/renderer/__tests__/editor-shortcuts.test.ts src/renderer/__tests__/focus-mode.test.tsx`
Expected: PASS.

- [ ] **Step 5: Typecheck + lint**

Run: `npm run typecheck && npx eslint --max-warnings 0 src/renderer/lib/editor-shortcuts.ts src/renderer/lib/focus-mode.ts src/renderer/components/FocusBar.tsx src/renderer/__tests__/editor-shortcuts.test.ts src/renderer/__tests__/focus-mode.test.tsx`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/renderer/lib/editor-shortcuts.ts src/renderer/lib/focus-mode.ts src/renderer/components/FocusBar.tsx src/renderer/__tests__/editor-shortcuts.test.ts src/renderer/__tests__/focus-mode.test.tsx
git commit -m "feat(editor): focus-mode state, ⌘. / Esc handling and focus bar"
```

---

### Task 3: Focus mode in the app shell and the editor

**Files:**
- Modify: `desktop/src/renderer/App.tsx`
- Modify: `desktop/src/renderer/components/RichMarkdownEditor.tsx`
- Modify: `desktop/src/renderer/styles.css` (append)
- Modify: `desktop/src/renderer/__tests__/App.test.tsx`
- Modify: `desktop/src/renderer/__tests__/RichMarkdownEditor.test.tsx`

**Interfaces:**
- Consumes: `useFocusActive`, `useFocusModeShortcuts`, `useFocusSurfaces` (Task 2).
- Produces: a new `RichMarkdownEditorProps.focus?: boolean` (default `false`). When true, the formatting toolbar isn't rendered and the root carries `data-focus="on"`. It flows through `GuardedNoteEditor`'s `editorProps` unchanged, because that type is `Omit<RichMarkdownEditorProps, 'markdown' | 'onSave'>`.

- [ ] **Step 1: Write the failing tests**

Append inside `describe('RichMarkdownEditor', …)` in `desktop/src/renderer/__tests__/RichMarkdownEditor.test.tsx`:

```tsx
  it('focus hides the formatting toolbar and marks the page for centring', () => {
    const { rerender } = render(
      <RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" focus />,
    );
    expect(screen.queryByRole('button', { name: 'bold' })).toBeNull();
    expect(screen.getByTestId('rich-markdown-editor')).toHaveAttribute('data-focus', 'on');
    rerender(<RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" />);
    expect(screen.getByRole('button', { name: 'bold' })).toBeInTheDocument();
    expect(screen.getByTestId('rich-markdown-editor')).not.toHaveAttribute('data-focus');
  });
```

In `desktop/src/renderer/__tests__/App.test.tsx`, change the vitest import to `import { describe, it, expect, beforeEach, afterEach } from 'vitest';`, change the testing-library import to `import { render, screen, fireEvent, act } from '@testing-library/react';`, and add:

```tsx
import { useSettings } from '../stores/settings';
import { useFocusSurfaces } from '../lib/focus-mode';
```

Add after the existing `beforeEach`:

```tsx
afterEach(() => {
  useSettings.setState({ focusMode: false });
  useFocusSurfaces.setState({ count: 0 });
});
```

Append inside `describe('App', …)`:

```tsx
  it('focus mode hides the sidebar and status bar only while an editor surface is up', async () => {
    wrap();
    await screen.findByRole('button', { name: 'activity' });
    expect(document.querySelector('.gb-statusbar')).not.toBeNull();

    // Flag on but nothing to edit on screen: chrome stays.
    act(() => useSettings.setState({ focusMode: true }));
    expect(screen.getByRole('button', { name: 'activity' })).toBeInTheDocument();

    let release!: () => void;
    act(() => {
      release = useFocusSurfaces.getState().register();
    });
    expect(screen.queryByRole('button', { name: 'activity' })).toBeNull();
    expect(document.querySelector('.gb-statusbar')).toBeNull();

    act(() => release());
    expect(await screen.findByRole('button', { name: 'activity' })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/renderer/__tests__/RichMarkdownEditor.test.tsx src/renderer/__tests__/App.test.tsx`
Expected: FAIL. The `bold` button is still present with `focus`, and the `activity` button is still present after `register()`.

- [ ] **Step 3: Implement**

`desktop/src/renderer/components/RichMarkdownEditor.tsx`, four additive edits:

1. In `interface RichMarkdownEditorProps`, after `openCameraSignal?: number;`:

```ts
  /** Focus mode (A4): hide the formatting toolbar and centre the page. */
  focus?: boolean;
```

2. In the function's destructured props, after `openCameraSignal,`:

```ts
  focus = false,
```

3. Replace the root opening tag

```tsx
    <div className="flex h-full flex-col" data-testid="rich-markdown-editor">
```

with

```tsx
    <div
      className="flex h-full flex-col"
      data-testid="rich-markdown-editor"
      data-focus={focus ? 'on' : undefined}
    >
```

4. Replace

```tsx
      {mode === 'rich' && editor && <EditorToolbar editor={editor} onPhoto={() => setCamOpen(true)} />}
```

with

```tsx
      {mode === 'rich' && editor && !focus && (
        <EditorToolbar editor={editor} onPhoto={() => setCamOpen(true)} />
      )}
```

`desktop/src/renderer/App.tsx`:

Add imports:

```tsx
import { useFocusActive, useFocusModeShortcuts } from './lib/focus-mode';
```

After `const setFailed = useSidecar((s) => s.setFailed);` (before the first `useEffect`, so the hooks run before the early returns):

```tsx
  const focusActive = useFocusActive();
  useFocusModeShortcuts();
```

In the returned JSX, replace `<Sidebar />` with `{!focusActive && <Sidebar />}` and `<StatusBar />` with `{!focusActive && <StatusBar />}`.

Append to `desktop/src/renderer/styles.css`:

```css
/* A4 focus mode: the page alone, centred at a reading measure. */
[data-focus='on'] .ProseMirror {
  max-width: 72ch;
  margin-left: auto;
  margin-right: auto;
  padding-top: 24px;
  padding-bottom: 30vh;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run src/renderer/__tests__/RichMarkdownEditor.test.tsx src/renderer/__tests__/App.test.tsx src/renderer/__tests__/GuardedNoteEditor.test.tsx`
Expected: PASS.

- [ ] **Step 5: Typecheck + lint**

Run: `npm run typecheck && npx eslint --max-warnings 0 src/renderer/App.tsx src/renderer/components/RichMarkdownEditor.tsx src/renderer/__tests__/App.test.tsx src/renderer/__tests__/RichMarkdownEditor.test.tsx`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/renderer/App.tsx src/renderer/components/RichMarkdownEditor.tsx src/renderer/styles.css src/renderer/__tests__/App.test.tsx src/renderer/__tests__/RichMarkdownEditor.test.tsx
git commit -m "feat(editor): focus mode hides app chrome and the formatting toolbar"
```

---

### Task 4: Focus mode in the jots screen and the note viewer

**Files:**
- Modify: `desktop/src/renderer/screens/jots.tsx`
- Modify: `desktop/src/renderer/components/NoteView.tsx`
- Modify: `desktop/src/renderer/__tests__/jots.test.tsx`
- Modify: `desktop/src/renderer/__tests__/NoteView.test.tsx`

**Interfaces:**
- Consumes: `useFocusSurface`, `useFocusActive`, `focusActiveNow`, `setFocusMode`, `useFocusSurfaces` (Task 2); `FocusBar` (Task 2); `shortcutLabel` (Task 2); `RichMarkdownEditorProps.focus` (Task 3).
- Produces: a focus button with accessible name `` `focus mode (${shortcutLabel('focus')})` `` (`focus mode (⌘ .)` in tests, where the platform is `darwin`) in the jots top bar and the note-viewer header.

- [ ] **Step 1: Write the failing tests**

Append to `desktop/src/renderer/__tests__/jots.test.tsx`, after the existing `describe('JotsScreen', …)` block. Add `afterEach` to the vitest import, and add `import { useSettings } from '../stores/settings';` and `import { useFocusSurfaces } from '../lib/focus-mode';`.

```tsx
describe('JotsScreen focus mode', () => {
  beforeEach(() => {
    useSettings.setState({ focusMode: false });
    useFocusSurfaces.setState({ count: 0 });
    apiRequest.mockImplementation(
      withConnectors(async (_m, path) => {
        if (path.includes('source=manual')) return { ok: true, status: 200, data: page };
        return { ok: true, status: 200, data: detail };
      }),
    );
  });

  afterEach(() => {
    useSettings.setState({ focusMode: false });
    useFocusSurfaces.setState({ count: 0 });
  });

  it('the focus button turns focus mode on', async () => {
    render(withQuery(<JotsScreen />));
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'focus mode (⌘ .)' }));
    await waitFor(() => expect(useSettings.getState().focusMode).toBe(true));
  });

  it('hides the tree, search, footer, backlinks and toolbar; exit restores them', async () => {
    useSettings.setState({ focusMode: true });
    render(withQuery(<JotsScreen />));
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());

    expect(screen.queryByPlaceholderText('search jots…')).toBeNull();
    expect(screen.queryByRole('region', { name: 'backlinks' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'bold' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'delete' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'jots' })).toBeNull();
    expect(screen.getByTestId('rich-markdown-editor')).toHaveAttribute('data-focus', 'on');

    fireEvent.click(screen.getByRole('button', { name: 'exit focus mode' }));
    await waitFor(() =>
      expect(screen.getByPlaceholderText('search jots…')).toBeInTheDocument(),
    );
    expect(screen.getByRole('button', { name: 'bold' })).toBeInTheDocument();
  });
});
```

Append inside `describe('NoteView', …)` in `desktop/src/renderer/__tests__/NoteView.test.tsx`. Add `import { useSettings } from '../stores/settings';` and `import { useFocusSurfaces } from '../lib/focus-mode';`. In the existing `beforeEach`, add `useSettings.setState({ focusMode: false }); useFocusSurfaces.setState({ count: 0 });`.

```tsx
  it('in focus mode the viewer drops its header and backlinks, and Esc does not close it', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: manualNote });
    useSettings.setState({ focusMode: true });
    render(withQuery(<NoteView />));
    act(() => useNoteView.getState().open(manualNote.path));
    await screen.findByText('hand-written');

    expect(screen.getByTestId('focus-bar')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'close' })).toBeNull();
    expect(screen.queryByRole('region', { name: 'backlinks' })).toBeNull();
    expect(screen.getByTestId('rich-markdown-editor')).toHaveAttribute('data-focus', 'on');

    // Without App's focus hook mounted, nothing leaves focus — but the viewer
    // must still not treat this Esc as "close".
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(useNoteView.getState().path).toBe(manualNote.path);
  });

  it('without focus mode Esc still closes the viewer', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: manualNote });
    render(withQuery(<NoteView />));
    act(() => useNoteView.getState().open(manualNote.path));
    await screen.findByText('hand-written');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(useNoteView.getState().path).toBeNull();
  });

  it('the header focus button turns focus mode on', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: manualNote });
    render(withQuery(<NoteView />));
    act(() => useNoteView.getState().open(manualNote.path));
    await screen.findByText('hand-written');
    fireEvent.click(screen.getByRole('button', { name: 'focus mode (⌘ .)' }));
    await waitFor(() => expect(useSettings.getState().focusMode).toBe(true));
    expect(await screen.findByTestId('focus-bar')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run src/renderer/__tests__/jots.test.tsx src/renderer/__tests__/NoteView.test.tsx`
Expected: FAIL. There is no `focus mode (⌘ .)` button, the search field is still present, and Esc closes the viewer.

- [ ] **Step 3: Implement in `screens/jots.tsx`**

Add imports:

```tsx
import { FocusBar } from '../components/FocusBar';
import { setFocusMode, useFocusActive, useFocusSurface } from '../lib/focus-mode';
import { shortcutLabel } from '../lib/editor-shortcuts';
```

Directly after `const editorInitial = initialBodyRef.current?.id === selectedId ? initialBodyRef.current : undefined;`:

```tsx
  // Focus mode (A4) applies only while a jot is open in the editor.
  useFocusSurface(editorInitial !== undefined);
  const focusActive = useFocusActive();
```

Replace the whole `<TopBar … />` element with:

```tsx
      {focusActive ? (
        <FocusBar />
      ) : (
        <TopBar
          title="jots"
          subtitle={list.data ? `${list.data.total} total` : '…'}
          right={
            <div className="flex gap-2">
              <Btn
                variant="ghost"
                size="sm"
                icon={<Lucide name="maximize-2" size={13} />}
                onClick={() => void setFocusMode(true)}
                disabled={editorInitial === undefined}
                ariaLabel={`focus mode (${shortcutLabel('focus')})`}
              />
              {/* existing assist / camera / new buttons, unchanged */}
            </div>
          }
        />
      )}
```

Keep the three existing `<Btn>` elements (assist, camera, new) exactly as they are, inside the `<div className="flex gap-2">` after the new focus button. The comment line above marks where they go; don't leave it in the code.

Wrap the search row: `{!focusActive && ( <div className="flex flex-shrink-0 border-b border-hairline px-4 py-2"> …input… </div> )}`.

Wrap the tree: `{!focusActive && ( <aside className="w-[260px] …"> … </aside> )}`.

Change `{selectedItem && <BacklinksPanel path={selectedItem.path} onOpen={openNote} />}` to:

```tsx
              {selectedItem && !focusActive && (
                <BacklinksPanel path={selectedItem.path} onOpen={openNote} />
              )}
```

Wrap the jot `<footer className="flex items-center gap-2 border-t …"> … </footer>` in `{!focusActive && ( … )}`.

In the `GuardedNoteEditor` `editorProps` object, add `focus: focusActive,` as the first property.

Change the assist aside condition `{assistOpen && selectedId && (` to `{assistOpen && selectedId && !focusActive && (`.

- [ ] **Step 4: Implement in `components/NoteView.tsx`**

Add imports:

```tsx
import { FocusBar } from './FocusBar';
import { focusActiveNow, setFocusMode, useFocusActive, useFocusSurface } from '../lib/focus-mode';
import { shortcutLabel } from '../lib/editor-shortcuts';
```

Replace the Esc handler body:

```tsx
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRef.current();
    };
```

with:

```tsx
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      // In focus mode the first Esc belongs to focus mode (App's hook leaves
      // it); only a later Esc closes the viewer.
      if (focusActiveNow()) return;
      closeRef.current();
    };
```

Directly after `const initial = initialBodyRef.current?.path === path ? initialBodyRef.current : undefined;` (before `if (path === null) return null;`):

```tsx
  useFocusSurface(initial !== undefined);
  const focusActive = useFocusActive();
```

Replace the inner panel's `className="flex h-full w-[820px] max-w-[92vw] flex-col border-l border-hairline bg-paper shadow-xl"` with:

```tsx
        className={
          focusActive
            ? 'flex h-full w-full flex-col bg-paper'
            : 'flex h-full w-[820px] max-w-[92vw] flex-col border-l border-hairline bg-paper shadow-xl'
        }
```

Wrap the `<header …> … </header>` as `{focusActive ? <FocusBar /> : ( <header …> … </header> )}`. Inside the header, add this button directly before the `open in editor` `<Btn>`:

```tsx
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="maximize-2" size={13} />}
            onClick={() => void setFocusMode(true)}
            ariaLabel={`focus mode (${shortcutLabel('focus')})`}
          />
```

Change `<BacklinksPanel path={path} onOpen={openNote} />` to `{!focusActive && <BacklinksPanel path={path} onOpen={openNote} />}`.

In the `GuardedNoteEditor` `editorProps` object, add `focus: focusActive,` as the first property.

- [ ] **Step 5: Run tests to verify they pass**

Run: `npx vitest run src/renderer/__tests__/jots.test.tsx src/renderer/__tests__/NoteView.test.tsx src/renderer/__tests__/focus-mode.test.tsx`
Expected: PASS, including the existing conflict-banner Esc test in `NoteView.test.tsx`.

- [ ] **Step 6: Typecheck + lint**

Run: `npm run typecheck && npx eslint --max-warnings 0 src/renderer/screens/jots.tsx src/renderer/components/NoteView.tsx src/renderer/__tests__/jots.test.tsx src/renderer/__tests__/NoteView.test.tsx`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/renderer/screens/jots.tsx src/renderer/components/NoteView.tsx src/renderer/__tests__/jots.test.tsx src/renderer/__tests__/NoteView.test.tsx
git commit -m "feat(jots): focus mode in the jots screen and note viewer"
```

---

### Task 5: Speech text extraction

**Files:**
- Create: `desktop/src/renderer/lib/read-aloud/segments.ts`
- Create: `desktop/src/renderer/lib/read-aloud/language.ts`
- Create: `desktop/src/renderer/__tests__/read-aloud-segments.test.ts`

**Interfaces:**
- Consumes: `buildEditorExtensions()` (tests only, to build real documents).
- Produces:
  - `interface SpeechSegment { from: number; to: number; text: string }`. `from` and `to` are the doc range of the sentence (for the highlight); `text` is what the voice says.
  - `collectSegments(doc: PMNode, range?: { from: number; to: number }): SpeechSegment[]`
  - `speakable(raw: string): string`
  - `startIndexFor(segments: SpeechSegment[], pos: number): number`
  - `type NoteLanguage = 'af' | 'en'` and `detectLanguage(text: string): NoteLanguage | null`.

- [ ] **Step 1: Write the failing test**

`desktop/src/renderer/__tests__/read-aloud-segments.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { Editor } from '@tiptap/core';
import type { Node as PMNode } from '@tiptap/pm/model';
import { buildEditorExtensions } from '../lib/editor/extensions';
import {
  collectSegments,
  speakable,
  startIndexFor,
} from '../lib/read-aloud/segments';
import { detectLanguage } from '../lib/read-aloud/language';

function docOf(markdown: string): PMNode {
  const editor = new Editor({ extensions: buildEditorExtensions(), content: markdown });
  const doc = editor.state.doc;
  editor.destroy();
  return doc;
}

function posOf(doc: PMNode, needle: string): number {
  let found = -1;
  doc.descendants((node, pos) => {
    if (found !== -1) return false;
    if (node.isText) {
      const i = node.text!.indexOf(needle);
      if (i !== -1) found = pos + i;
    }
    return true;
  });
  if (found === -1) throw new Error(`not found: ${needle}`);
  return found;
}

const texts = (doc: PMNode, range?: { from: number; to: number }) =>
  collectSegments(doc, range).map((s) => s.text);

describe('collectSegments', () => {
  it('reads rendered text sentence by sentence, never markdown syntax', () => {
    expect(texts(docOf('# Title\n\nSome **bold** text. Second sentence!'))).toEqual([
      'Title',
      'Some bold text.',
      'Second sentence!',
    ]);
  });

  it('skips fenced code blocks, including mermaid', () => {
    const doc = docOf('Before.\n\n```js\nconst x = 1;\n```\n\n```mermaid\nflowchart TD\n```\n\nAfter.');
    expect(texts(doc)).toEqual(['Before.', 'After.']);
  });

  it('reads list items and table cells', () => {
    const doc = docOf('- first item\n- second item\n\n| a | b |\n| --- | --- |\n| one | two |');
    expect(texts(doc)).toEqual(['first item', 'second item', 'a', 'b', 'one', 'two']);
  });

  it('skips punctuation-only paragraphs', () => {
    expect(texts(docOf('Hello.\n\n— …'))).toEqual(['Hello.']);
  });

  it('maps each sentence to its exact doc range', () => {
    const doc = docOf('One. Two.');
    const segs = collectSegments(doc);
    expect(segs).toHaveLength(2);
    expect(doc.textBetween(segs[0]!.from, segs[0]!.to)).toBe('One.');
    expect(doc.textBetween(segs[1]!.from, segs[1]!.to)).toBe('Two.');
  });

  it('keeps positions aligned across a hard break', () => {
    const doc = docOf('Line one  \nline two.');
    const segs = collectSegments(doc);
    expect(segs.map((s) => s.text)).toEqual(['Line one line two.']);
    expect(segs[0]!.to - segs[0]!.from).toBe('Line one line two.'.length);
    expect(doc.textBetween(segs[0]!.to - 4, segs[0]!.to)).toBe('two.');
  });

  it('a selection reads only the selected part', () => {
    const doc = docOf('Alpha one. Beta two. Gamma three.');
    const from = posOf(doc, 'Beta');
    expect(texts(doc, { from, to: posOf(doc, 'two.') + 4 })).toEqual(['Beta two.']);
    expect(texts(doc, { from: posOf(doc, 'two'), to: posOf(doc, 'two.') + 4 })).toEqual(['two.']);
  });

  it('a selection spanning paragraphs clips both ends', () => {
    const doc = docOf('First para ends here.\n\nSecond para starts now.');
    const range = { from: posOf(doc, 'ends'), to: posOf(doc, 'para starts') + 4 };
    expect(texts(doc, range)).toEqual(['ends here.', 'Second para']);
  });
});

describe('speakable', () => {
  it('turns wikilinks into their alias or note name', () => {
    expect(speakable('See [[20-contexts/work/notes/plan|the plan]] now')).toBe('See the plan now');
    expect(speakable('Ask [[30-cross-context/people/alex|@Alex]]')).toBe('Ask Alex');
    expect(speakable('Open [[20-contexts/work/notes/roadmap.md]]')).toBe('Open roadmap');
  });

  it('reads tags as words and urls as "link"', () => {
    expect(speakable('Filed under #project/alpha and #todo.')).toBe(
      'Filed under project alpha and todo.',
    );
    expect(speakable('Docs at https://example.com/a?b=c today')).toBe('Docs at link today');
  });

  it('leaves a C# style hash inside a word alone', () => {
    expect(speakable('We use C# here')).toBe('We use C# here');
  });
});

describe('startIndexFor', () => {
  const doc = docOf('Alpha one. Beta two. Gamma three.');
  const segs = collectSegments(doc);

  it('starts at the sentence containing the cursor', () => {
    expect(startIndexFor(segs, posOf(doc, 'two'))).toBe(1);
    expect(startIndexFor(segs, posOf(doc, 'Alpha'))).toBe(0);
  });

  it('starts from the top when the cursor is past the last sentence', () => {
    expect(startIndexFor(segs, doc.content.size)).toBe(0);
  });
});

describe('detectLanguage', () => {
  it('recognises Afrikaans', () => {
    expect(detectLanguage('Ek het die vergadering bygewoon en ons sal more weer praat.')).toBe('af');
  });

  it('recognises English', () => {
    expect(detectLanguage('The team agreed that the release is ready for the review.')).toBe('en');
  });

  it('returns null for short or mixed text', () => {
    expect(detectLanguage('ok')).toBeNull();
    expect(detectLanguage('die the en and ek with')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/renderer/__tests__/read-aloud-segments.test.ts`
Expected: FAIL with "Failed to resolve import '../lib/read-aloud/segments'".

- [ ] **Step 3: Write the implementation**

`desktop/src/renderer/lib/read-aloud/segments.ts`:

```ts
import type { Node as PMNode } from '@tiptap/pm/model';

/** One sentence to speak. `from`/`to` are the doc range (for the highlight);
 * `text` is what the voice says, with markdown-only noise removed. */
export interface SpeechSegment {
  from: number;
  to: number;
  text: string;
}

const SENTENCES = new Intl.Segmenter(undefined, { granularity: 'sentence' });
const WIKILINK = /\[\[([^\][|]+?)(?:\|([^\]]+))?\]\]/g;
const URL_RE = /\bhttps?:\/\/\S+/gi;
const TAG = /(^|\s)#([\p{L}\p{N}_][\p{L}\p{N}_/-]*)/gu;
const HAS_WORD = /[\p{L}\p{N}]/u;

/** Spoken form of a sentence: wikilinks → alias (or note name), tags → words,
 * bare URLs → "link", whitespace collapsed. */
export function speakable(raw: string): string {
  return raw
    .replace(WIKILINK, (_m: string, target: string, alias?: string) => {
      const label = alias ?? (target.split('/').pop() ?? target).replace(/\.md$/, '');
      return label.replace(/^@/, '');
    })
    .replace(URL_RE, 'link')
    .replace(TAG, (_m: string, pre: string, tag: string) => `${pre}${tag.replace(/[/_-]+/g, ' ')}`)
    .replace(/\s+/g, ' ')
    .trim();
}

/** Sentences of every textblock in document order. Code blocks (any node
 * whose spec says `code: true`, which includes mermaid fences) are skipped.
 * Inline non-text nodes (hard break, status lozenge) count as spaces of their
 * node size, so char index i ↔ doc position contentStart + i holds exactly.
 * With `range`, only the part inside it is returned (partial sentences
 * clipped). */
export function collectSegments(
  doc: PMNode,
  range?: { from: number; to: number },
): SpeechSegment[] {
  const out: SpeechSegment[] = [];
  doc.descendants((node, pos) => {
    if (node.type.spec.code) return false;
    if (!node.isTextblock) return true;
    const contentStart = pos + 1;
    let text = '';
    node.forEach((child) => {
      text += child.isText ? (child.text ?? '') : ' '.repeat(child.nodeSize);
    });
    const lo = range ? Math.max(0, range.from - contentStart) : 0;
    const hi = range ? Math.min(text.length, range.to - contentStart) : text.length;
    if (hi <= lo) return false;
    for (const s of SENTENCES.segment(text)) {
      let a = Math.max(s.index, lo);
      let b = Math.min(s.index + s.segment.length, hi);
      while (a < b && /\s/.test(text[a]!)) a++;
      while (b > a && /\s/.test(text[b - 1]!)) b--;
      if (b <= a) continue;
      const spoken = speakable(text.slice(a, b));
      if (!HAS_WORD.test(spoken)) continue;
      out.push({ from: contentStart + a, to: contentStart + b, text: spoken });
    }
    return false;
  });
  return out;
}

/** Index of the sentence containing `pos` (or the next one after it); 0 when
 * the cursor is past the last sentence, so "read" starts from the top. */
export function startIndexFor(segments: SpeechSegment[], pos: number): number {
  const i = segments.findIndex((s) => s.to > pos);
  return i === -1 ? 0 : i;
}
```

`desktop/src/renderer/lib/read-aloud/language.ts`:

```ts
export type NoteLanguage = 'af' | 'en';

// Distinctive, frequent function words only; words common to both languages
// ("is", "was", "met", "in") are left out on purpose.
const AF = new Set([
  'die', 'het', 'nie', 'van', 'en', 'ek', 'jy', 'ons', 'vir', 'ook', 'maar', 'sal', 'wat', 'hulle', 'word',
]);
const EN = new Set([
  'the', 'and', 'of', 'to', 'that', 'with', 'for', 'this', 'are', 'you', 'it', 'on', 'be', 'have', 'not',
]);

/** Dominant language of a note, for picking a read-aloud voice. Needs at
 * least three marker words and a 1.5× lead; otherwise null (use the default
 * voice). */
export function detectLanguage(text: string): NoteLanguage | null {
  const words = text.toLowerCase().match(/\p{L}+/gu) ?? [];
  let af = 0;
  let en = 0;
  for (const w of words) {
    if (AF.has(w)) af++;
    else if (EN.has(w)) en++;
  }
  if (af + en < 3) return null;
  if (af > en * 1.5) return 'af';
  if (en > af * 1.5) return 'en';
  return null;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/renderer/__tests__/read-aloud-segments.test.ts`
Expected: PASS. If `reads list items and table cells` fails on the table half because GFM parsing differs, check the parsed doc with `doc.toJSON()`. Only adjust the fixture if the table shape is genuinely different; never change the implementation to special-case tables.

- [ ] **Step 5: Typecheck + lint**

Run: `npm run typecheck && npx eslint --max-warnings 0 src/renderer/lib/read-aloud/segments.ts src/renderer/lib/read-aloud/language.ts src/renderer/__tests__/read-aloud-segments.test.ts`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/renderer/lib/read-aloud/segments.ts src/renderer/lib/read-aloud/language.ts src/renderer/__tests__/read-aloud-segments.test.ts
git commit -m "feat(read-aloud): sentence segments from the editor doc + language guess"
```

---

### Task 6: Sentence highlight plugin

**Files:**
- Create: `desktop/src/renderer/lib/read-aloud/highlight.ts`
- Create: `desktop/src/renderer/__tests__/read-aloud-highlight.test.ts`
- Modify: `desktop/src/renderer/styles.css` (append)

**Interfaces:**
- Consumes: Tiptap `Editor.registerPlugin` / `Editor.unregisterPlugin`.
- Produces:
  - `interface HighlightRange { from: number; to: number }`
  - `readAloudKey: PluginKey<DecorationSet>` and `READ_ALOUD_CLASS = 'gb-read-aloud-current'`
  - `readAloudHighlightPlugin(): Plugin<DecorationSet>`
  - `attachReadAloudHighlight(editor: Editor): () => void` (idempotent; returns detach)
  - `setReadAloudHighlight(editor: Editor, range: HighlightRange | null): void` (no-op when the editor is destroyed or the plugin isn't attached)
  - `currentHighlight(editor: Editor): HighlightRange | null`

- [ ] **Step 1: Write the failing test**

`desktop/src/renderer/__tests__/read-aloud-highlight.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Editor } from '@tiptap/core';
import { buildEditorExtensions } from '../lib/editor/extensions';
import {
  READ_ALOUD_CLASS,
  attachReadAloudHighlight,
  currentHighlight,
  setReadAloudHighlight,
} from '../lib/read-aloud/highlight';

let editor: Editor | null = null;

function make(content: string, onUpdate = vi.fn()) {
  editor = new Editor({
    element: document.createElement('div'),
    extensions: buildEditorExtensions(),
    content,
    onUpdate,
  });
  return editor;
}

function highlighted(ed: Editor): string {
  return Array.from(ed.view.dom.querySelectorAll(`.${READ_ALOUD_CLASS}`))
    .map((n) => n.textContent)
    .join('');
}

afterEach(() => {
  editor?.destroy();
  editor = null;
});

describe('read-aloud highlight', () => {
  it('decorates the given range', () => {
    const ed = make('One. Two.');
    attachReadAloudHighlight(ed);
    setReadAloudHighlight(ed, { from: 6, to: 10 });
    expect(highlighted(ed)).toBe('Two.');
    expect(currentHighlight(ed)).toEqual({ from: 6, to: 10 });
  });

  it('null clears it', () => {
    const ed = make('One. Two.');
    attachReadAloudHighlight(ed);
    setReadAloudHighlight(ed, { from: 1, to: 5 });
    setReadAloudHighlight(ed, null);
    expect(highlighted(ed)).toBe('');
    expect(currentHighlight(ed)).toBeNull();
  });

  it('never changes the doc, fires no update and adds no undo step', () => {
    const onUpdate = vi.fn();
    const ed = make('One. Two.', onUpdate);
    attachReadAloudHighlight(ed);
    const before = ed.getJSON();
    setReadAloudHighlight(ed, { from: 1, to: 5 });
    expect(ed.getJSON()).toEqual(before);
    expect(onUpdate).not.toHaveBeenCalled();
    expect(ed.can().undo()).toBe(false);
  });

  it('maps the highlight through edits', () => {
    const ed = make('One. Two.');
    attachReadAloudHighlight(ed);
    setReadAloudHighlight(ed, { from: 6, to: 10 });
    ed.view.dispatch(ed.state.tr.insertText('New. ', 1));
    expect(highlighted(ed)).toBe('Two.');
  });

  it('clamps out-of-range ranges instead of throwing', () => {
    const ed = make('One.');
    attachReadAloudHighlight(ed);
    expect(() => setReadAloudHighlight(ed, { from: 3, to: 999 })).not.toThrow();
    expect(highlighted(ed)).toBe('e.');
    expect(() => setReadAloudHighlight(ed, { from: 999, to: 1200 })).not.toThrow();
    expect(highlighted(ed)).toBe('');
  });

  it('attach is idempotent and detach removes the plugin', () => {
    const ed = make('One. Two.');
    const detach = attachReadAloudHighlight(ed);
    attachReadAloudHighlight(ed);
    setReadAloudHighlight(ed, { from: 1, to: 5 });
    expect(highlighted(ed)).toBe('One.');
    detach();
    expect(highlighted(ed)).toBe('');
    expect(() => setReadAloudHighlight(ed, { from: 1, to: 5 })).not.toThrow();
    expect(highlighted(ed)).toBe('');
  });

  it('is safe after the editor is destroyed', () => {
    const ed = make('One.');
    const detach = attachReadAloudHighlight(ed);
    ed.destroy();
    editor = null;
    expect(() => setReadAloudHighlight(ed, { from: 1, to: 2 })).not.toThrow();
    expect(() => detach()).not.toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/renderer/__tests__/read-aloud-highlight.test.ts`
Expected: FAIL with "Failed to resolve import '../lib/read-aloud/highlight'".

- [ ] **Step 3: Write the implementation**

`desktop/src/renderer/lib/read-aloud/highlight.ts`:

```ts
import type { Editor } from '@tiptap/core';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';

export interface HighlightRange {
  from: number;
  to: number;
}

export const readAloudKey = new PluginKey<DecorationSet>('gbReadAloud');
export const READ_ALOUD_CLASS = 'gb-read-aloud-current';

/** Decoration-only: the document is never modified, so the markdown on disk
 * and the autosave path are untouched. Set via a meta transaction; mapped
 * through user edits. */
export function readAloudHighlightPlugin(): Plugin<DecorationSet> {
  return new Plugin<DecorationSet>({
    key: readAloudKey,
    state: {
      init: () => DecorationSet.empty,
      apply(tr, set) {
        const meta = tr.getMeta(readAloudKey) as HighlightRange | null | undefined;
        if (meta === undefined) return set.map(tr.mapping, tr.doc);
        if (meta === null) return DecorationSet.empty;
        const size = tr.doc.content.size;
        const from = Math.max(0, Math.min(meta.from, size));
        const to = Math.max(from, Math.min(meta.to, size));
        if (to <= from) return DecorationSet.empty;
        return DecorationSet.create(tr.doc, [
          Decoration.inline(from, to, { class: READ_ALOUD_CLASS }),
        ]);
      },
    },
    props: {
      decorations: (state) => readAloudKey.getState(state),
    },
  });
}

function attached(editor: Editor): boolean {
  return !editor.isDestroyed && readAloudKey.getState(editor.state) !== undefined;
}

/** Registered at runtime (not in buildEditorExtensions) so the editor schema
 * and A1's extension list stay untouched. */
export function attachReadAloudHighlight(editor: Editor): () => void {
  if (!editor.isDestroyed && !attached(editor)) editor.registerPlugin(readAloudHighlightPlugin());
  return () => {
    if (attached(editor)) editor.unregisterPlugin(readAloudKey);
  };
}

export function setReadAloudHighlight(editor: Editor, range: HighlightRange | null): void {
  if (!attached(editor)) return;
  editor.view.dispatch(
    editor.state.tr.setMeta(readAloudKey, range).setMeta('addToHistory', false),
  );
}

export function currentHighlight(editor: Editor): HighlightRange | null {
  if (!attached(editor)) return null;
  const d = readAloudKey.getState(editor.state)?.find()[0];
  return d ? { from: d.from, to: d.to } : null;
}
```

Append to `desktop/src/renderer/styles.css`:

```css
/* A4 read-aloud: the sentence being spoken. */
.gb-read-aloud-current {
  background: var(--neon-mist);
  border-radius: 2px;
  box-shadow: 0 0 0 2px var(--neon-mist);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/renderer/__tests__/read-aloud-highlight.test.ts`
Expected: PASS.

- [ ] **Step 5: Typecheck + lint**

Run: `npm run typecheck && npx eslint --max-warnings 0 src/renderer/lib/read-aloud/highlight.ts src/renderer/__tests__/read-aloud-highlight.test.ts`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/renderer/lib/read-aloud/highlight.ts src/renderer/__tests__/read-aloud-highlight.test.ts src/renderer/styles.css
git commit -m "feat(read-aloud): decoration-only current-sentence highlight"
```

---

### Task 7: Read-aloud playback controller

**Files:**
- Create: `desktop/src/renderer/lib/read-aloud/controller.ts`
- Create: `desktop/src/renderer/__tests__/helpers/fake-speech.ts`
- Create: `desktop/src/renderer/__tests__/read-aloud-controller.test.ts`

**Interfaces:**
- Consumes: `SpeechSegment` (Task 5).
- Produces:
  - `type ReadAloudStatus = 'idle' | 'playing' | 'paused'`
  - `interface SpeechEngine { speak(u: SpeechSynthesisUtterance): void; cancel(): void }` (`window.speechSynthesis` satisfies it)
  - `interface SpeakOptions { voice: SpeechSynthesisVoice | null; rate: number }`
  - `interface ReadAloudCallbacks { onHighlight(segment: SpeechSegment | null): void; onStatus(status: ReadAloudStatus): void; onError(message: string): void }`
  - `class ReadAloudController(engine: SpeechEngine, makeUtterance: (text: string) => SpeechSynthesisUtterance, cb: ReadAloudCallbacks)` with `start(segments: SpeechSegment[], startIndex: number, opts: SpeakOptions): void`, `pause(): void`, `resume(): void`, `stop(): void`, `mapPositions(map: (pos: number, assoc?: number) => number): void`, `readonly status: ReadAloudStatus`, `readonly currentSegment: SpeechSegment | null`.
  - The test helper `__tests__/helpers/fake-speech.ts` exports `FakeUtterance`, `FakeSynth` (`spoken`, `cancel` (a `vi.fn`), `voices`, `speak`, `getVoices`, `addEventListener`, `removeEventListener`, `setVoices(v)`, `last`, `texts()`), `end(u)`, `fail(u, error)`, `fakeVoice(name, lang, extra?)`, `installFakeSpeech(): FakeSynth` and `uninstallFakeSpeech(): void`. Tasks 8–10 use it.

- [ ] **Step 1: Write the test helper**

`desktop/src/renderer/__tests__/helpers/fake-speech.ts`:

```ts
import { vi } from 'vitest';

/** jsdom has no speechSynthesis — a minimal, inspectable stand-in. */
export class FakeUtterance {
  text: string;
  voice: SpeechSynthesisVoice | null = null;
  rate = 1;
  lang = '';
  onstart: ((ev: unknown) => void) | null = null;
  onend: ((ev: unknown) => void) | null = null;
  onerror: ((ev: { error: string }) => void) | null = null;
  constructor(text: string) {
    this.text = text;
  }
}

export class FakeSynth {
  spoken: FakeUtterance[] = [];
  cancel = vi.fn();
  voices: SpeechSynthesisVoice[] = [];
  private listeners = new Set<() => void>();

  speak(u: SpeechSynthesisUtterance): void {
    this.spoken.push(u as unknown as FakeUtterance);
  }
  getVoices(): SpeechSynthesisVoice[] {
    return this.voices;
  }
  addEventListener(type: string, fn: () => void): void {
    if (type === 'voiceschanged') this.listeners.add(fn);
  }
  removeEventListener(type: string, fn: () => void): void {
    if (type === 'voiceschanged') this.listeners.delete(fn);
  }
  /** Simulates the OS finishing its async voice load. */
  setVoices(v: SpeechSynthesisVoice[]): void {
    this.voices = v;
    this.listeners.forEach((fn) => fn());
  }
  get last(): FakeUtterance | undefined {
    return this.spoken[this.spoken.length - 1];
  }
  texts(): string[] {
    return this.spoken.map((u) => u.text);
  }
}

export function end(u: FakeUtterance | undefined): void {
  u?.onend?.({});
}

export function fail(u: FakeUtterance | undefined, error: string): void {
  u?.onerror?.({ error });
}

export function fakeVoice(
  name: string,
  lang: string,
  extra: Partial<SpeechSynthesisVoice> = {},
): SpeechSynthesisVoice {
  return {
    name,
    lang,
    voiceURI: `${name}-uri`,
    localService: true,
    default: false,
    ...extra,
  } as SpeechSynthesisVoice;
}

const targets = (): Array<Record<string, unknown>> => [
  globalThis as unknown as Record<string, unknown>,
  window as unknown as Record<string, unknown>,
];

export function installFakeSpeech(): FakeSynth {
  const synth = new FakeSynth();
  for (const t of targets()) {
    t.speechSynthesis = synth;
    t.SpeechSynthesisUtterance = FakeUtterance;
  }
  return synth;
}

export function uninstallFakeSpeech(): void {
  for (const t of targets()) {
    delete t.speechSynthesis;
    delete t.SpeechSynthesisUtterance;
  }
}
```

- [ ] **Step 2: Write the failing test**

`desktop/src/renderer/__tests__/read-aloud-controller.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { ReadAloudController, type ReadAloudStatus } from '../lib/read-aloud/controller';
import type { SpeechSegment } from '../lib/read-aloud/segments';
import { FakeSynth, FakeUtterance, end, fail, fakeVoice } from './helpers/fake-speech';

const SEGS: SpeechSegment[] = [
  { from: 1, to: 5, text: 'One.' },
  { from: 6, to: 10, text: 'Two.' },
  { from: 11, to: 17, text: 'Three.' },
];
const OPTS = { voice: null, rate: 1 };

function setup() {
  const synth = new FakeSynth();
  const highlights: Array<SpeechSegment | null> = [];
  const statuses: ReadAloudStatus[] = [];
  const errors: string[] = [];
  const ctrl = new ReadAloudController(
    synth,
    (t) => new FakeUtterance(t) as unknown as SpeechSynthesisUtterance,
    {
      onHighlight: (s) => highlights.push(s),
      onStatus: (s) => statuses.push(s),
      onError: (m) => errors.push(m),
    },
  );
  return { synth, ctrl, highlights, statuses, errors };
}

describe('ReadAloudController', () => {
  it('speaks from the start index, one utterance per sentence, highlighting each', () => {
    const { synth, ctrl, highlights, statuses } = setup();
    ctrl.start(SEGS, 1, OPTS);
    expect(synth.texts()).toEqual(['Two.']);
    expect(highlights).toEqual([SEGS[1]]);
    expect(statuses).toEqual(['playing']);
    end(synth.last);
    expect(synth.texts()).toEqual(['Two.', 'Three.']);
    expect(highlights.at(-1)).toEqual(SEGS[2]);
  });

  it('finishing the last sentence goes idle and clears the highlight', () => {
    const { synth, ctrl, highlights, statuses } = setup();
    ctrl.start(SEGS, 2, OPTS);
    end(synth.last);
    expect(ctrl.status).toBe('idle');
    expect(highlights.at(-1)).toBeNull();
    expect(statuses).toEqual(['playing', 'idle']);
  });

  it('applies voice and rate to every utterance', () => {
    const { synth, ctrl } = setup();
    const daniel = fakeVoice('Daniel', 'en-GB');
    ctrl.start(SEGS, 0, { voice: daniel, rate: 1.5 });
    end(synth.last);
    for (const u of synth.spoken) {
      expect(u.voice).toBe(daniel);
      expect(u.lang).toBe('en-GB');
      expect(u.rate).toBe(1.5);
    }
  });

  it('pause cancels and keeps the highlight; resume restarts the same sentence', () => {
    const { synth, ctrl, highlights } = setup();
    ctrl.start(SEGS, 0, OPTS);
    ctrl.pause();
    expect(synth.cancel).toHaveBeenCalled();
    expect(ctrl.status).toBe('paused');
    expect(highlights.at(-1)).toEqual(SEGS[0]);
    ctrl.resume();
    expect(synth.texts()).toEqual(['One.', 'One.']);
    expect(ctrl.status).toBe('playing');
  });

  it('ignores a late end/error from a paused or stopped utterance', () => {
    const { synth, ctrl, errors } = setup();
    ctrl.start(SEGS, 0, OPTS);
    const first = synth.last;
    ctrl.pause();
    fail(first, 'interrupted');
    end(first);
    expect(synth.spoken).toHaveLength(1);
    expect(ctrl.status).toBe('paused');

    ctrl.resume();
    const second = synth.last;
    ctrl.stop();
    fail(second, 'canceled');
    end(second);
    expect(synth.spoken).toHaveLength(2);
    expect(ctrl.status).toBe('idle');
    expect(errors).toEqual([]);
  });

  it('a new start supersedes the old run', () => {
    const { synth, ctrl } = setup();
    ctrl.start(SEGS, 0, OPTS);
    const old = synth.last;
    ctrl.start(SEGS, 2, OPTS);
    end(old);
    expect(synth.texts()).toEqual(['One.', 'Three.']);
  });

  it('stop cancels, clears the highlight and goes idle', () => {
    const { synth, ctrl, highlights } = setup();
    ctrl.start(SEGS, 0, OPTS);
    ctrl.stop();
    expect(synth.cancel).toHaveBeenCalled();
    expect(highlights.at(-1)).toBeNull();
    expect(ctrl.status).toBe('idle');
    expect(ctrl.currentSegment).toBeNull();
  });

  it('an engine failure stops and reports the error', () => {
    const { synth, ctrl, errors, highlights } = setup();
    ctrl.start(SEGS, 0, OPTS);
    fail(synth.last, 'synthesis-unavailable');
    expect(errors).toEqual(['synthesis-unavailable']);
    expect(ctrl.status).toBe('idle');
    expect(highlights.at(-1)).toBeNull();
  });

  it('empty segments stay idle and speak nothing', () => {
    const { synth, ctrl, statuses } = setup();
    ctrl.start([], 0, OPTS);
    expect(synth.spoken).toHaveLength(0);
    expect(statuses).toEqual([]);
  });

  it('clamps an out-of-range start index to the last sentence', () => {
    const { synth, ctrl } = setup();
    ctrl.start(SEGS, 9, OPTS);
    expect(synth.texts()).toEqual(['Three.']);
  });

  it('mapPositions shifts the queued ranges', () => {
    const { ctrl } = setup();
    ctrl.start(SEGS, 0, OPTS);
    ctrl.mapPositions((p) => p + 3);
    expect(ctrl.currentSegment).toEqual({ from: 4, to: 8, text: 'One.' });
  });

  it('pause and resume are no-ops in the wrong state', () => {
    const { synth, ctrl } = setup();
    ctrl.pause();
    ctrl.resume();
    expect(synth.spoken).toHaveLength(0);
    expect(ctrl.status).toBe('idle');
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npx vitest run src/renderer/__tests__/read-aloud-controller.test.ts`
Expected: FAIL with "Failed to resolve import '../lib/read-aloud/controller'".

- [ ] **Step 4: Write the implementation**

`desktop/src/renderer/lib/read-aloud/controller.ts`:

```ts
import type { SpeechSegment } from './segments';

export type ReadAloudStatus = 'idle' | 'playing' | 'paused';

/** The two calls we need from window.speechSynthesis (fakeable in tests). */
export interface SpeechEngine {
  speak(u: SpeechSynthesisUtterance): void;
  cancel(): void;
}

export interface SpeakOptions {
  voice: SpeechSynthesisVoice | null;
  rate: number;
}

export interface ReadAloudCallbacks {
  onHighlight(segment: SpeechSegment | null): void;
  onStatus(status: ReadAloudStatus): void;
  onError(message: string): void;
}

/** Error codes that mean "we cancelled it", not "the engine failed". */
const BENIGN = new Set(['interrupted', 'canceled']);

/** Speaks segments one utterance per sentence. Every speak bumps `gen`, and
 * every event handler checks it, so the async end/error that Chromium fires
 * for a cancelled utterance can never advance or restart playback. Pause =
 * cancel + remember the sentence; resume re-speaks it from its start. */
export class ReadAloudController {
  private segments: SpeechSegment[] = [];
  private index = 0;
  private gen = 0;
  private opts: SpeakOptions = { voice: null, rate: 1 };
  private _status: ReadAloudStatus = 'idle';
  // Chromium can drop events of an utterance nothing references any more.
  private current: SpeechSynthesisUtterance | null = null;

  constructor(
    private readonly engine: SpeechEngine,
    private readonly makeUtterance: (text: string) => SpeechSynthesisUtterance,
    private readonly cb: ReadAloudCallbacks,
  ) {}

  get status(): ReadAloudStatus {
    return this._status;
  }

  get currentSegment(): SpeechSegment | null {
    return this._status === 'idle' ? null : (this.segments[this.index] ?? null);
  }

  start(segments: SpeechSegment[], startIndex: number, opts: SpeakOptions): void {
    this.gen++;
    this.engine.cancel();
    if (segments.length === 0) {
      this.reset();
      return;
    }
    this.segments = segments.slice();
    this.opts = opts;
    this.index = Math.min(Math.max(0, startIndex), segments.length - 1);
    this.speakCurrent();
  }

  pause(): void {
    if (this._status !== 'playing') return;
    this.gen++;
    this.engine.cancel();
    this.current = null;
    this.setStatus('paused');
  }

  resume(): void {
    if (this._status !== 'paused') return;
    this.speakCurrent();
  }

  stop(): void {
    this.gen++;
    this.engine.cancel();
    this.reset();
  }

  /** Keep queued ranges valid while the user edits during playback. */
  mapPositions(map: (pos: number, assoc?: number) => number): void {
    this.segments = this.segments.map((s) => {
      const from = map(s.from, 1);
      return { ...s, from, to: Math.max(from, map(s.to, -1)) };
    });
  }

  private speakCurrent(): void {
    const seg = this.segments[this.index];
    if (!seg) {
      this.reset();
      return;
    }
    const gen = ++this.gen;
    const u = this.makeUtterance(seg.text);
    if (this.opts.voice) {
      u.voice = this.opts.voice;
      u.lang = this.opts.voice.lang;
    }
    u.rate = this.opts.rate;
    u.onend = () => {
      if (gen !== this.gen) return;
      this.index++;
      this.speakCurrent();
    };
    u.onerror = (e: SpeechSynthesisErrorEvent) => {
      if (gen !== this.gen || BENIGN.has(e.error)) return;
      this.gen++;
      this.engine.cancel();
      this.reset();
      this.cb.onError(e.error);
    };
    this.current = u;
    this.cb.onHighlight(seg);
    this.setStatus('playing');
    this.engine.speak(u);
  }

  private reset(): void {
    const wasActive = this._status !== 'idle';
    this.segments = [];
    this.index = 0;
    this.current = null;
    if (wasActive) this.cb.onHighlight(null);
    this.setStatus('idle');
  }

  private setStatus(s: ReadAloudStatus): void {
    if (s === this._status) return;
    this._status = s;
    this.cb.onStatus(s);
  }
}
```

If lint flags `current` as unused, keep the field (it is the GC anchor) and read it in a getter, `get speaking(): boolean { return this.current !== null; }`, rather than removing it.

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest run src/renderer/__tests__/read-aloud-controller.test.ts`
Expected: PASS.

- [ ] **Step 6: Typecheck + lint**

Run: `npm run typecheck && npx eslint --max-warnings 0 src/renderer/lib/read-aloud/controller.ts src/renderer/__tests__/helpers/fake-speech.ts src/renderer/__tests__/read-aloud-controller.test.ts`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/renderer/lib/read-aloud/controller.ts src/renderer/__tests__/helpers/fake-speech.ts src/renderer/__tests__/read-aloud-controller.test.ts
git commit -m "feat(read-aloud): per-sentence playback controller with stale-event guard"
```

---

### Task 8: Offline voice selection

**Files:**
- Create: `desktop/src/renderer/lib/read-aloud/voices.ts`
- Create: `desktop/src/renderer/__tests__/read-aloud-voices.test.tsx`

**Interfaces:**
- Consumes: `NoteLanguage` (Task 5); `fake-speech` helper (Task 7).
- Produces:
  - `isSpeechSupported(): boolean`
  - `localVoices(all: readonly SpeechSynthesisVoice[]): SpeechSynthesisVoice[]` (only `localService`, sorted by `lang` then `name`)
  - `useSpeechVoices(): SpeechSynthesisVoice[]` (local voices, live on `voiceschanged`)
  - `pickVoice(voices: readonly SpeechSynthesisVoice[], preferredUri: string, lang: NoteLanguage | null): SpeechSynthesisVoice | null`
  - `makeUtterance(text: string): SpeechSynthesisUtterance`
  - `previewVoice(voice: SpeechSynthesisVoice | null, rate: number): void`

- [ ] **Step 1: Write the failing test**

`desktop/src/renderer/__tests__/read-aloud-voices.test.tsx`:

```tsx
import { afterEach, describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import {
  isSpeechSupported,
  localVoices,
  pickVoice,
  previewVoice,
  useSpeechVoices,
} from '../lib/read-aloud/voices';
import { fakeVoice, installFakeSpeech, uninstallFakeSpeech } from './helpers/fake-speech';

afterEach(() => uninstallFakeSpeech());

const SAMANTHA = fakeVoice('Samantha', 'en-US', { default: true });
const DANIEL = fakeVoice('Daniel', 'en-GB');
const AF = fakeVoice('Afrikaans', 'af-ZA');
const NETWORK = fakeVoice('Cloud', 'en-US', { localService: false });

describe('voices', () => {
  it('isSpeechSupported reflects the API being present', () => {
    expect(isSpeechSupported()).toBe(false);
    installFakeSpeech();
    expect(isSpeechSupported()).toBe(true);
  });

  it('localVoices drops network voices and sorts by language then name', () => {
    expect(localVoices([SAMANTHA, NETWORK, AF, DANIEL]).map((v) => v.name)).toEqual([
      'Afrikaans',
      'Daniel',
      'Samantha',
    ]);
  });

  it('pickVoice: an installed explicit choice wins', () => {
    expect(pickVoice([SAMANTHA, DANIEL, AF], 'Daniel-uri', 'af')).toBe(DANIEL);
  });

  it('pickVoice: a missing explicit choice falls back to auto', () => {
    expect(pickVoice([SAMANTHA, DANIEL, AF], 'Gone-uri', 'af')).toBe(AF);
    expect(pickVoice([SAMANTHA, DANIEL], 'Gone-uri', null)).toBe(SAMANTHA);
  });

  it('pickVoice: auto matches the note language, preferring the default voice', () => {
    expect(pickVoice([DANIEL, SAMANTHA, AF], '', 'af')).toBe(AF);
    expect(pickVoice([DANIEL, SAMANTHA], '', 'en')).toBe(SAMANTHA);
    expect(pickVoice([DANIEL], '', 'en')).toBe(DANIEL);
  });

  it('pickVoice: no voice for the language falls back to the OS default, then null', () => {
    expect(pickVoice([SAMANTHA, DANIEL], '', 'af')).toBe(SAMANTHA);
    expect(pickVoice([DANIEL], '', 'af')).toBeNull();
    expect(pickVoice([], '', null)).toBeNull();
  });

  it('useSpeechVoices picks up voices that load late', () => {
    const synth = installFakeSpeech();
    const { result } = renderHook(() => useSpeechVoices());
    expect(result.current).toEqual([]);
    act(() => synth.setVoices([SAMANTHA, NETWORK]));
    expect(result.current.map((v) => v.name)).toEqual(['Samantha']);
  });

  it('useSpeechVoices is empty and harmless without speech support', () => {
    const { result } = renderHook(() => useSpeechVoices());
    expect(result.current).toEqual([]);
  });

  it('previewVoice cancels anything playing and speaks a sample with voice and rate', () => {
    const synth = installFakeSpeech();
    previewVoice(DANIEL, 1.3);
    expect(synth.cancel).toHaveBeenCalled();
    expect(synth.last?.voice).toBe(DANIEL);
    expect(synth.last?.rate).toBe(1.3);
    expect(synth.last?.text).toMatch(/poltergeist/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/renderer/__tests__/read-aloud-voices.test.tsx`
Expected: FAIL with "Failed to resolve import '../lib/read-aloud/voices'".

- [ ] **Step 3: Write the implementation**

`desktop/src/renderer/lib/read-aloud/voices.ts`:

```ts
import { useEffect, useState } from 'react';
import type { NoteLanguage } from './language';

/** Web Speech runs in Chromium's browser process (platform TTS: AVSpeech /
 * NSSpeechSynthesizer on macOS, SAPI on Windows); the sandboxed renderer only
 * needs the API to exist. */
export function isSpeechSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'speechSynthesis' in window &&
    typeof window.SpeechSynthesisUtterance === 'function'
  );
}

/** Offline voices only: the user approved OS voices, never a network TTS. */
export function localVoices(all: readonly SpeechSynthesisVoice[]): SpeechSynthesisVoice[] {
  return all
    .filter((v) => v.localService)
    .sort((a, b) => a.lang.localeCompare(b.lang) || a.name.localeCompare(b.name));
}

/** Local voices, refreshed on `voiceschanged` (Chromium loads them async). */
export function useSpeechVoices(): SpeechSynthesisVoice[] {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>(() =>
    isSpeechSupported() ? localVoices(window.speechSynthesis.getVoices()) : [],
  );
  useEffect(() => {
    if (!isSpeechSupported()) return;
    const synth = window.speechSynthesis;
    const update = () => setVoices(localVoices(synth.getVoices()));
    update();
    synth.addEventListener('voiceschanged', update);
    return () => synth.removeEventListener('voiceschanged', update);
  }, []);
  return voices;
}

function baseLang(v: SpeechSynthesisVoice): string {
  return v.lang.toLowerCase().replace('_', '-').split('-')[0] ?? '';
}

/** Explicit, installed choice → that voice. Otherwise (auto, or the chosen
 * voice was uninstalled): a voice for the note's language, preferring the OS
 * default among them; else the OS default voice; else null (engine default). */
export function pickVoice(
  voices: readonly SpeechSynthesisVoice[],
  preferredUri: string,
  lang: NoteLanguage | null,
): SpeechSynthesisVoice | null {
  if (preferredUri) {
    const chosen = voices.find((v) => v.voiceURI === preferredUri);
    if (chosen) return chosen;
  }
  if (lang) {
    const matches = voices.filter((v) => baseLang(v) === lang);
    if (matches.length > 0) return matches.find((v) => v.default) ?? matches[0]!;
  }
  return voices.find((v) => v.default) ?? null;
}

export function makeUtterance(text: string): SpeechSynthesisUtterance {
  return new window.SpeechSynthesisUtterance(text);
}

export function previewVoice(voice: SpeechSynthesisVoice | null, rate: number): void {
  if (!isSpeechSupported()) return;
  const u = makeUtterance('this is how poltergeist reads your notes.');
  if (voice) {
    u.voice = voice;
    u.lang = voice.lang;
  }
  u.rate = rate;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(u);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/renderer/__tests__/read-aloud-voices.test.tsx`
Expected: PASS.

- [ ] **Step 5: Typecheck + lint**

Run: `npm run typecheck && npx eslint --max-warnings 0 src/renderer/lib/read-aloud/voices.ts src/renderer/__tests__/read-aloud-voices.test.tsx`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/renderer/lib/read-aloud/voices.ts src/renderer/__tests__/read-aloud-voices.test.tsx
git commit -m "feat(read-aloud): offline voice list and language-aware voice choice"
```

---

### Task 9: Read-aloud controls in the editor

**Files:**
- Create: `desktop/src/renderer/components/ReadAloudControls.tsx`
- Create: `desktop/src/renderer/__tests__/ReadAloudControls.test.tsx`
- Modify: `desktop/src/renderer/components/RichMarkdownEditor.tsx` (one import, one footer line)

**Interfaces:**
- Consumes: `collectSegments`, `startIndexFor`, `SpeechSegment` (Task 5); `detectLanguage` (Task 5); `attachReadAloudHighlight`, `setReadAloudHighlight` (Task 6); `ReadAloudController`, `ReadAloudStatus` (Task 7); `isSpeechSupported`, `makeUtterance`, `pickVoice`, `useSpeechVoices` (Task 8); `matchesShortcut`, `shortcutLabel` (Task 2); `Settings.readAloudVoice` and `Settings.readAloudRate` (Task 1).
- Produces: `ReadAloudControls({ editor }: { editor: Editor })`. It renders `null` when speech is unsupported. Otherwise it renders `role="group"` `aria-label="read aloud controls"` with buttons named `` `read aloud (${shortcutLabel('readAloud')})` `` (idle), `pause reading` (playing), `resume reading` (paused) and `stop reading` (playing or paused).

- [ ] **Step 1: Write the failing test**

`desktop/src/renderer/__tests__/ReadAloudControls.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';
import { useSettings } from '../stores/settings';
import { useToasts } from '../stores/toast';
import {
  end,
  fail,
  fakeVoice,
  installFakeSpeech,
  uninstallFakeSpeech,
  type FakeSynth,
} from './helpers/fake-speech';

let synth: FakeSynth;

beforeEach(() => {
  synth = installFakeSpeech();
  useSettings.setState({ readAloudVoice: '', readAloudRate: 1 });
  useToasts.setState({ toasts: [] });
});

afterEach(() => uninstallFakeSpeech());

function renderEditor(markdown: string) {
  const onSave = vi.fn();
  let editor: Editor | undefined;
  const utils = render(
    <RichMarkdownEditor
      markdown={markdown}
      onSave={onSave}
      jotId="t"
      debounceMs={10}
      onEditorReady={(e) => {
        editor = e;
      }}
    />,
  );
  return { ...utils, onSave, editor: () => editor! };
}

const readButton = () => screen.getByRole('button', { name: /^read aloud/ });

function highlighted(container: HTMLElement): string {
  return Array.from(container.querySelectorAll('.gb-read-aloud-current'))
    .map((n) => n.textContent)
    .join('');
}

function posOf(editor: Editor, needle: string): number {
  let found = -1;
  editor.state.doc.descendants((node, pos) => {
    if (found !== -1) return false;
    if (node.isText) {
      const i = node.text!.indexOf(needle);
      if (i !== -1) found = pos + i;
    }
    return true;
  });
  if (found === -1) throw new Error(`not found: ${needle}`);
  return found;
}

describe('ReadAloudControls', () => {
  it('hides the read button when speech synthesis is unavailable', () => {
    uninstallFakeSpeech();
    renderEditor('Hello there.');
    expect(screen.queryByRole('button', { name: /^read aloud/ })).toBeNull();
  });

  it('reads the note sentence by sentence and highlights the current one', () => {
    const { container } = renderEditor('# Plan\n\nFirst point. Second point.');
    fireEvent.click(readButton());
    expect(synth.texts()).toEqual(['Plan']);
    expect(highlighted(container)).toBe('Plan');
    act(() => end(synth.last));
    expect(highlighted(container)).toBe('First point.');
    act(() => end(synth.last));
    act(() => end(synth.last));
    expect(synth.texts()).toEqual(['Plan', 'First point.', 'Second point.']);
    expect(highlighted(container)).toBe('');
    expect(readButton()).toBeInTheDocument();
  });

  it('pause cancels, resume restarts the same sentence, stop clears', () => {
    const { container } = renderEditor('One. Two.');
    fireEvent.click(readButton());
    const first = synth.last;
    fireEvent.click(screen.getByRole('button', { name: 'pause reading' }));
    expect(synth.cancel).toHaveBeenCalled();
    act(() => fail(first, 'interrupted'));
    act(() => end(first));
    expect(synth.texts()).toEqual(['One.']);
    expect(highlighted(container)).toBe('One.');
    fireEvent.click(screen.getByRole('button', { name: 'resume reading' }));
    expect(synth.texts()).toEqual(['One.', 'One.']);
    fireEvent.click(screen.getByRole('button', { name: 'stop reading' }));
    expect(highlighted(container)).toBe('');
    expect(readButton()).toBeInTheDocument();
  });

  it('reads only the selection when there is one', () => {
    const h = renderEditor('Alpha one. Beta two. Gamma three.');
    const ed = h.editor();
    act(() => {
      ed.commands.setTextSelection({ from: posOf(ed, 'Beta'), to: posOf(ed, 'two.') + 4 });
    });
    fireEvent.click(readButton());
    act(() => end(synth.last));
    expect(synth.texts()).toEqual(['Beta two.']);
  });

  it('reads from the cursor to the end of the note', () => {
    const h = renderEditor('Alpha one. Beta two. Gamma three.');
    const ed = h.editor();
    act(() => {
      ed.commands.setTextSelection(posOf(ed, 'two'));
    });
    fireEvent.click(readButton());
    act(() => end(synth.last));
    expect(synth.texts()).toEqual(['Beta two.', 'Gamma three.']);
  });

  it('auto voice picks an Afrikaans voice for an Afrikaans note', () => {
    synth.voices = [fakeVoice('Samantha', 'en-US', { default: true }), fakeVoice('Afrikaans', 'af-ZA')];
    renderEditor('Ek het die vergadering bygewoon en ons sal more weer praat.');
    fireEvent.click(readButton());
    expect(synth.last?.voice?.lang).toBe('af-ZA');
  });

  it('an explicit voice and rate from settings win', () => {
    synth.voices = [fakeVoice('Samantha', 'en-US', { default: true }), fakeVoice('Daniel', 'en-GB')];
    useSettings.setState({ readAloudVoice: 'Daniel-uri', readAloudRate: 1.5 });
    renderEditor('Hello there.');
    fireEvent.click(readButton());
    expect(synth.last?.voice?.name).toBe('Daniel');
    expect(synth.last?.rate).toBe(1.5);
  });

  it('an engine failure stops reading with a toast', () => {
    renderEditor('One. Two.');
    fireEvent.click(readButton());
    act(() => fail(synth.last, 'synthesis-failed'));
    expect(
      useToasts.getState().toasts.some((t) => t.message.includes('synthesis-failed')),
    ).toBe(true);
    expect(readButton()).toBeInTheDocument();
  });

  it('a note with only code says there is nothing to read', () => {
    renderEditor('```js\nconst x = 1;\n```');
    fireEvent.click(readButton());
    expect(synth.spoken).toHaveLength(0);
    expect(
      useToasts.getState().toasts.some((t) => t.message === 'nothing to read here'),
    ).toBe(true);
  });

  it('unmounting (note switch) stops speech and ignores the late end event', () => {
    const h = renderEditor('One. Two.');
    fireEvent.click(readButton());
    const u = synth.last;
    h.unmount();
    expect(synth.cancel).toHaveBeenCalled();
    end(u);
    expect(synth.spoken).toHaveLength(1);
  });

  it('⌘⇧L in the editor toggles reading', () => {
    const h = renderEditor('One. Two.');
    const dom = h.editor().view.dom;
    fireEvent.keyDown(dom, { key: 'L', metaKey: true, shiftKey: true });
    expect(synth.texts()).toEqual(['One.']);
    fireEvent.keyDown(dom, { key: 'L', metaKey: true, shiftKey: true });
    expect(screen.getByRole('button', { name: 'resume reading' })).toBeInTheDocument();
  });

  it('the highlight never triggers an autosave and follows edits', async () => {
    const h = renderEditor('One. Two.');
    const ed = h.editor();
    fireEvent.click(readButton());
    act(() => end(synth.last));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(h.onSave).not.toHaveBeenCalled();
    act(() => {
      ed.view.dispatch(ed.state.tr.insertText('New. ', 1));
    });
    expect(highlighted(h.container)).toBe('Two.');
  });

  it('switching to source mode stops reading and hides the controls', () => {
    renderEditor('One. Two.');
    fireEvent.click(readButton());
    fireEvent.click(screen.getByRole('button', { name: 'src' }));
    expect(synth.cancel).toHaveBeenCalled();
    expect(screen.queryByRole('group', { name: 'read aloud controls' })).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/renderer/__tests__/ReadAloudControls.test.tsx`
Expected: FAIL. `getByRole('button', { name: /^read aloud/ })` finds nothing. The first test (unsupported) passes trivially.

- [ ] **Step 3: Write the component**

`desktop/src/renderer/components/ReadAloudControls.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react';
import type { Editor } from '@tiptap/core';
import type { Transaction } from '@tiptap/pm/state';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { isMac } from '../lib/platform';
import { matchesShortcut, shortcutLabel } from '../lib/editor-shortcuts';
import { collectSegments, startIndexFor, type SpeechSegment } from '../lib/read-aloud/segments';
import { detectLanguage } from '../lib/read-aloud/language';
import { attachReadAloudHighlight, setReadAloudHighlight } from '../lib/read-aloud/highlight';
import { ReadAloudController, type ReadAloudStatus } from '../lib/read-aloud/controller';
import {
  isSpeechSupported,
  makeUtterance,
  pickVoice,
  useSpeechVoices,
} from '../lib/read-aloud/voices';
import { Btn } from './Btn';
import { Lucide } from './Lucide';

/** Scroll the spoken sentence into view; best effort (jsdom has no
 * scrollIntoView, and the view can be detached during unmount). */
function reveal(editor: Editor, seg: SpeechSegment): void {
  try {
    const { node } = editor.view.domAtPos(seg.from);
    const el = node.nodeType === 1 ? (node as Element) : node.parentElement;
    el?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  } catch {
    // view not attached — nothing to scroll
  }
}

/** ▶ read / pause / resume / stop for one editor instance (A4). Reads the
 * selection, or from the cursor to the end; ⌘⇧L / Ctrl+Shift+L toggles while
 * the editor has focus. Unmount (note switch, source mode) stops speech. */
export function ReadAloudControls({ editor }: { editor: Editor }) {
  const supported = isSpeechSupported();
  const voices = useSpeechVoices();
  const voiceUri = useSettings((s) => s.readAloudVoice);
  const rate = useSettings((s) => s.readAloudRate);
  const [status, setStatus] = useState<ReadAloudStatus>('idle');
  const ctrlRef = useRef<ReadAloudController | null>(null);
  const optsRef = useRef({ voices, voiceUri, rate });
  optsRef.current = { voices, voiceUri, rate };

  useEffect(() => {
    if (!supported) return;
    const detach = attachReadAloudHighlight(editor);
    const ctrl = new ReadAloudController(window.speechSynthesis, makeUtterance, {
      onHighlight: (seg) => {
        setReadAloudHighlight(editor, seg ? { from: seg.from, to: seg.to } : null);
        if (seg) reveal(editor, seg);
      },
      onStatus: setStatus,
      onError: (msg) => toast.error(`read-aloud stopped: ${msg}`),
    });
    ctrlRef.current = ctrl;
    const onTransaction = ({ transaction }: { transaction: Transaction }) => {
      if (transaction.docChanged) {
        ctrl.mapPositions((pos, assoc) => transaction.mapping.map(pos, assoc));
      }
    };
    editor.on('transaction', onTransaction);
    return () => {
      editor.off('transaction', onTransaction);
      ctrl.stop();
      ctrlRef.current = null;
      detach();
    };
  }, [editor, supported]);

  const toggle = () => {
    const ctrl = ctrlRef.current;
    if (!ctrl) return;
    if (ctrl.status === 'playing') return ctrl.pause();
    if (ctrl.status === 'paused') return ctrl.resume();
    const { from, to, empty } = editor.state.selection;
    const doc = editor.state.doc;
    const segments = empty ? collectSegments(doc) : collectSegments(doc, { from, to });
    if (segments.length === 0) {
      toast.info('nothing to read here');
      return;
    }
    const o = optsRef.current;
    ctrl.start(segments, empty ? startIndexFor(segments, from) : 0, {
      voice: pickVoice(o.voices, o.voiceUri, detectLanguage(doc.textContent)),
      rate: o.rate,
    });
  };
  const toggleRef = useRef(toggle);
  toggleRef.current = toggle;

  useEffect(() => {
    if (!supported) return;
    const dom = editor.view.dom;
    const onKey = (e: KeyboardEvent) => {
      if (!matchesShortcut(e, 'readAloud', isMac)) return;
      e.preventDefault();
      toggleRef.current();
    };
    dom.addEventListener('keydown', onKey);
    return () => dom.removeEventListener('keydown', onKey);
  }, [editor, supported]);

  if (!supported) return null;

  return (
    <div role="group" aria-label="read aloud controls" className="flex items-center gap-1">
      {status === 'idle' && (
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="play" size={12} />}
          onClick={toggle}
          ariaLabel={`read aloud (${shortcutLabel('readAloud')})`}
        >
          read
        </Btn>
      )}
      {status === 'playing' && (
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="pause" size={12} />}
          onClick={toggle}
          ariaLabel="pause reading"
        >
          pause
        </Btn>
      )}
      {status === 'paused' && (
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="play" size={12} />}
          onClick={toggle}
          ariaLabel="resume reading"
        >
          resume
        </Btn>
      )}
      {status !== 'idle' && (
        <Btn
          variant="ghost"
          size="sm"
          icon={<Lucide name="square" size={12} />}
          onClick={() => ctrlRef.current?.stop()}
          ariaLabel="stop reading"
        >
          stop
        </Btn>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Mount it in `RichMarkdownEditor.tsx`**

Add `import { ReadAloudControls } from './ReadAloudControls';`. In the footer strip, directly after the `copy formatted` block

```tsx
        {mode === 'rich' && (
          <Btn
            …
          >
            copy formatted
          </Btn>
        )}
```

add one line:

```tsx
        {mode === 'rich' && editor && <ReadAloudControls editor={editor} />}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npx vitest run src/renderer/__tests__/ReadAloudControls.test.tsx src/renderer/__tests__/RichMarkdownEditor.test.tsx src/renderer/__tests__/jots.test.tsx src/renderer/__tests__/NoteView.test.tsx`
Expected: PASS. jsdom has no `speechSynthesis`, so the existing suites don't see the controls.

- [ ] **Step 6: Typecheck + lint**

Run: `npm run typecheck && npx eslint --max-warnings 0 src/renderer/components/ReadAloudControls.tsx src/renderer/components/RichMarkdownEditor.tsx src/renderer/__tests__/ReadAloudControls.test.tsx`
Expected: no errors. If `react-hooks/exhaustive-deps` warns about `toggle`, leave the code as is. `toggle` is only called through `toggleRef` or as an onClick, so it's never an effect dependency.

- [ ] **Step 7: Commit**

```bash
git add src/renderer/components/ReadAloudControls.tsx src/renderer/components/RichMarkdownEditor.tsx src/renderer/__tests__/ReadAloudControls.test.tsx
git commit -m "feat(editor): read-aloud controls with sentence highlight and ⌘⇧L"
```

---

### Task 10: Settings › editor section

**Files:**
- Modify: `desktop/src/renderer/screens/settings.tsx`
- Create: `desktop/src/renderer/__tests__/EditorSettings.test.tsx`

**Interfaces:**
- Consumes: `Settings.readAloudVoice` and `Settings.readAloudRate` (Task 1); `shortcutLabel` (Task 2); `isSpeechSupported`, `useSpeechVoices`, `pickVoice`, `previewVoice` (Task 8); the local `SettingRow`, `SectionHeader`, `trySet`, `selectClass` and the existing `Btn`, `Lucide`, `Pill` imports in `settings.tsx`.
- Produces: the exported `EditorSettings()` and a new `SectionId` `'editor'` (nav label `editor`, icon `pen-line`). Controls: `combobox` `read-aloud voice`, `slider` `read-aloud speed`, button `play sample`.

- [ ] **Step 1: Write the failing test**

`desktop/src/renderer/__tests__/EditorSettings.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { EditorSettings, SettingsScreen } from '../screens/settings';
import { useSettings } from '../stores/settings';
import {
  fakeVoice,
  installFakeSpeech,
  uninstallFakeSpeech,
  type FakeSynth,
} from './helpers/fake-speech';

let synth: FakeSynth;

beforeEach(() => {
  synth = installFakeSpeech();
  synth.voices = [
    fakeVoice('Samantha', 'en-US', { default: true }),
    fakeVoice('Daniel', 'en-GB'),
    fakeVoice('Cloud', 'en-US', { localService: false }),
  ];
  useSettings.setState({ readAloudVoice: '', readAloudRate: 1 });
});

afterEach(() => {
  uninstallFakeSpeech();
  vi.restoreAllMocks();
});

const voiceSelect = () =>
  screen.getByRole('combobox', { name: 'read-aloud voice' }) as HTMLSelectElement;

describe('EditorSettings', () => {
  it('lists auto plus the offline voices only', () => {
    render(<EditorSettings />);
    expect(Array.from(voiceSelect().options).map((o) => o.textContent)).toEqual([
      'auto (match note language)',
      'Daniel — en-GB',
      'Samantha — en-US',
    ]);
  });

  it('choosing a voice saves it', async () => {
    const set = vi.spyOn(window.gb.settings, 'set');
    render(<EditorSettings />);
    fireEvent.change(voiceSelect(), { target: { value: 'Daniel-uri' } });
    await waitFor(() => expect(useSettings.getState().readAloudVoice).toBe('Daniel-uri'));
    expect(set).toHaveBeenCalledWith('readAloudVoice', 'Daniel-uri');
  });

  it('the speed slider saves a value rounded to one decimal', async () => {
    render(<EditorSettings />);
    fireEvent.change(screen.getByRole('slider', { name: 'read-aloud speed' }), {
      target: { value: '1.4000000000000001' },
    });
    await waitFor(() => expect(useSettings.getState().readAloudRate).toBe(1.4));
    expect(screen.getByText('1.4×')).toBeInTheDocument();
  });

  it('says when the chosen voice is no longer installed', () => {
    useSettings.setState({ readAloudVoice: 'Gone-uri' });
    render(<EditorSettings />);
    expect(screen.getByText(/no longer installed/)).toBeInTheDocument();
    expect(voiceSelect().value).toBe('');
  });

  it('play sample speaks with the chosen voice and speed', () => {
    useSettings.setState({ readAloudVoice: 'Daniel-uri', readAloudRate: 1.2 });
    render(<EditorSettings />);
    fireEvent.click(screen.getByRole('button', { name: /play sample/ }));
    expect(synth.last?.voice?.name).toBe('Daniel');
    expect(synth.last?.rate).toBe(1.2);
  });

  it('shows read-aloud as unavailable without speech synthesis', () => {
    uninstallFakeSpeech();
    render(<EditorSettings />);
    expect(screen.queryByRole('combobox', { name: 'read-aloud voice' })).toBeNull();
    expect(screen.getByText('unavailable')).toBeInTheDocument();
  });

  it('shows both editor shortcuts', () => {
    render(<EditorSettings />);
    expect(screen.getByText('⌘ .')).toBeInTheDocument();
    expect(screen.getByText('⌘ ⇧ L')).toBeInTheDocument();
  });

  it('is reachable from the settings nav', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SettingsScreen />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'editor' }));
    expect(screen.getByRole('heading', { name: 'editor' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/renderer/__tests__/EditorSettings.test.tsx`
Expected: FAIL. `EditorSettings` is not exported (it's undefined when rendered).

- [ ] **Step 3: Implement in `screens/settings.tsx`**

Add imports:

```tsx
import { shortcutLabel } from '../lib/editor-shortcuts';
import {
  isSpeechSupported,
  pickVoice,
  previewVoice,
  useSpeechVoices,
} from '../lib/read-aloud/voices';
```

Add `| 'editor'` to `type SectionId`. In `SECTIONS`, insert after the `display` entry:

```tsx
  { id: 'editor', label: 'editor', icon: 'pen-line' },
```

In `SettingsScreen`, after `{section === 'display' && <DisplaySettings />}`:

```tsx
          {section === 'editor' && <EditorSettings />}
```

Add the component (next to `DisplaySettings`):

```tsx
const kbdClass =
  'rounded-sm border border-hairline-2 bg-vellum px-[10px] py-1 font-mono text-11 text-ink-0';

export function EditorSettings() {
  const voiceUri = useSettings((s) => s.readAloudVoice);
  const rate = useSettings((s) => s.readAloudRate);
  const setSetting = useSettings((s) => s.set);
  const voices = useSpeechVoices();
  const supported = isSpeechSupported();
  // Only claim "missing" once voices have loaded; they arrive asynchronously.
  const missing =
    voiceUri !== '' && voices.length > 0 && !voices.some((v) => v.voiceURI === voiceUri);
  return (
    <div>
      <SectionHeader title="editor" sub="focus mode and read-aloud for jots and notes." />
      <SettingRow
        label="focus mode"
        sub="hide everything but the page you're writing. esc leaves."
        control={<kbd className={kbdClass}>{shortcutLabel('focus')}</kbd>}
      />
      {supported ? (
        <>
          <SettingRow
            label="read aloud"
            sub="reads the selection, or from the cursor to the end."
            control={<kbd className={kbdClass}>{shortcutLabel('readAloud')}</kbd>}
          />
          <SettingRow
            label="read-aloud voice"
            sub={
              missing
                ? 'the chosen voice is no longer installed — using auto.'
                : 'system voices, offline. auto matches the note language — afrikaans notes use an afrikaans voice when one is installed.'
            }
            control={
              <select
                aria-label="read-aloud voice"
                className={selectClass}
                value={missing ? '' : voiceUri}
                onChange={(e) => void trySet(setSetting, 'readAloudVoice', e.target.value)}
              >
                <option value="">auto (match note language)</option>
                {voices.map((v) => (
                  <option key={v.voiceURI} value={v.voiceURI}>
                    {v.name} — {v.lang}
                  </option>
                ))}
              </select>
            }
          />
          <SettingRow
            label="read-aloud speed"
            sub={`${rate.toFixed(1)}×`}
            control={
              <input
                type="range"
                aria-label="read-aloud speed"
                min={0.5}
                max={2}
                step={0.1}
                value={rate}
                onChange={(e) =>
                  void trySet(
                    setSetting,
                    'readAloudRate',
                    Math.round(Number(e.target.value) * 10) / 10,
                  )
                }
              />
            }
          />
          <SettingRow
            label="preview"
            sub="hear the voice at this speed."
            control={
              <Btn
                variant="secondary"
                size="sm"
                icon={<Lucide name="volume-2" size={12} />}
                onClick={() => previewVoice(pickVoice(voices, voiceUri, null), rate)}
              >
                play sample
              </Btn>
            }
          />
        </>
      ) : (
        <SettingRow
          label="read aloud"
          sub="speech isn't available on this system, so the read button is hidden."
          control={<Pill>unavailable</Pill>}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/renderer/__tests__/EditorSettings.test.tsx src/renderer/__tests__/MeetingSettings.test.tsx src/renderer/__tests__/AiProviderSettings.test.tsx`
Expected: PASS.

- [ ] **Step 5: Typecheck + lint**

Run: `npm run typecheck && npx eslint --max-warnings 0 src/renderer/screens/settings.tsx src/renderer/__tests__/EditorSettings.test.tsx`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add src/renderer/screens/settings.tsx src/renderer/__tests__/EditorSettings.test.tsx
git commit -m "feat(settings): editor section with read-aloud voice, speed and preview"
```

---

### Task 11: Full gates and platform smoke check

**Files:**
- None created. Fix only what the gates or the smoke check uncover, in the file that owns the bug, with a test that reproduces it first.

**Interfaces:**
- Consumes: everything above.
- Produces: a green branch, plus a short smoke-check note in the PR description.

- [ ] **Step 1: Run the full desktop gates**

Run: `npm run typecheck && npx vitest run && npm run lint`
Expected: all pass with zero lint warnings. A failure in `markdown-roundtrip.test.ts` means A4 touched the schema by mistake. A4 must not change it, so revert that change.

- [ ] **Step 2: Confirm the shared-file footprint is small**

Run: `git diff --stat origin/main -- src/renderer/components/RichMarkdownEditor.tsx src/renderer/styles.css src/renderer/lib/editor/`
Expected: no changes under `lib/editor/`. `RichMarkdownEditor.tsx` has ≤ 15 changed lines. `styles.css` has only the two appended A4 blocks.

- [ ] **Step 3: Manual smoke on macOS (`npm run dev`)**

Check each of these:
1. Open a jot and press ⌘. . The sidebar, tree, top bar, footer, backlinks and formatting toolbar disappear, and the page is centred. The window can still be dragged by the top strip, and the traffic lights don't overlap the exit button. Esc restores everything. Press ⌘. twice to toggle.
2. Open a vault note in the viewer, then press ⌘. . The viewer goes full width. The first Esc leaves focus; the second closes the viewer.
3. Type `/` to open the slash menu in focus mode and press Esc. The menu closes and focus mode stays.
4. Restart the app in focus mode. Today shows the sidebar. Opening a jot hides it.
5. Click **read**. You hear an OS voice, the sentence highlight moves, and the view scrolls with it. Pause, resume (the sentence restarts) and stop all work. ⌘⇧L toggles reading. Switching jots stops speech.
6. Select one sentence and click read: only that sentence is read. Put the cursor mid-note: reading starts there.
7. Settings › editor: the voice list shows system voices, and `play sample` speaks. A speed of 1.5× is audibly faster on the next read.
8. Turn Wi-Fi off and repeat step 5. Speech still works offline.

- [ ] **Step 4: Manual smoke on Windows (`npm run dev` on a Windows machine, or the release build)**

Repeat steps 1, 3, 5, 6 and 7 with Ctrl+. and Ctrl+Shift+L. Expected: SAPI voices (for example Microsoft David/Zira) are listed and speak. If `speechSynthesis.getVoices()` stays empty and the first read toasts `read-aloud stopped: synthesis-…`, record it in the PR and stop. Don't add a main-process fallback in this slice. That would need a new decision from the user.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A src/renderer
git commit -m "fix(read-aloud): <what the smoke check found>"
```

(Skip this step when nothing needed fixing.)

---

## Self-Review

**Spec coverage (section "Focus mode and read-aloud" plus "Error handling" and "Testing"):**
- Focus flag in `stores/settings`, persisted → Task 1 (`focusMode` key) and Task 2 (`setFocusMode`).
- Hide the sidebar nav → Task 3 (App). JotTree and the assist panel → Task 4. The toolbar → Task 3 (`focus` prop) and Task 4 (TopBar).
- Centre at 72ch → Task 3 CSS. Esc or ⌘. exits → Task 2, with precedence in Task 4.
- Web Speech API, offline, OS voices, no new dependency → Tasks 7–9; the mechanism is justified under Decisions.
- "▶ Read" reads the selection or from the cursor → Task 5 (`collectSegments` range, `startIndexFor`) and Task 9.
- Current-sentence decoration → Task 6, wired in Task 9.
- Voice and rate pickers in Settings › Editor → Task 10.
- Default voice by dominant language (Afrikaans → Afrikaans voice, otherwise the default) → Task 5 (`detectLanguage`), Task 8 (`pickVoice`), Task 9 test.
- Speech unavailable → Read hidden → Task 9 test (`hides the read button…`) and Task 10 (`unavailable`).
- Testing line "focus-mode toggling" → Tasks 2–4.

**Placeholder scan:** no TBD/TODO. The Task 4 TopBar snippet has a comment marking where the three existing buttons go, and the step says to keep them verbatim and not keep the comment. Task 11 Step 5's commit message is filled in with the actual finding at run time, and the step is skipped when nothing needs fixing.

**Type consistency:** `SpeechSegment {from,to,text}` is the same in Tasks 5, 7 and 9. `HighlightRange` is used in Task 6 and passed as `{from,to}` in Task 9. `ReadAloudStatus` and the `pause`/`resume`/`stop`/`start(segments, startIndex, opts)` signatures match between Tasks 7 and 9. `pickVoice(voices, preferredUri, lang)` matches between Tasks 8, 9 and 10. `matchesShortcut(e, which, mac)` and `shortcutLabel(which, mac?)` match between Tasks 2, 4, 9 and 10. `focusActiveNow`, `useFocusActive`, `useFocusSurface`, `useFocusSurfaces` and `setFocusMode` match between Tasks 2, 3 and 4. The fake-speech helper API (`installFakeSpeech`, `uninstallFakeSpeech`, `fakeVoice`, `end`, `fail`, `FakeSynth.texts/last/cancel/voices/setVoices`) matches every consumer.

**Review Focus:** each of the five lines names its pinning test, and each test appears in its owning task's Step 1.
