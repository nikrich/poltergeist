# A7 Confluence-Style Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the jots editor and the note viewer look and work like a Confluence page: a centred page canvas with a fixed/full width toggle, a breadcrumb, a big editable title, a byline (author, last updated, History, Backlinks), and one fixed formatting toolbar with a text-style dropdown, mark and list buttons, link, table and a "+ Insert" menu that lists every A1 block.

**Architecture:** The page title is a line of the note body, never frontmatter. `lib/editor/page-title.ts` splits the body into a raw *head* (the title line, kept byte for byte) and the *rest* (what TipTap edits), and joins them back for every save. `GuardedNoteEditor` gets an optional `page` prop. In page mode it owns the split, renders the page header (breadcrumb, `PageTitle`, byline) and sends every save, from the title or the body, through the same B1 guard, so the etag chain and the conflict banner cover both. `RichMarkdownEditor` renders that header above the document inside a new page canvas whose width comes from a global `pageWidth` setting. `EditorToolbar.tsx` is rewritten in place: its formatting actions live in `lib/editor/toolbar-actions.ts`, and its Insert menu (`lib/editor/insert-menu.ts`) runs A1's `SLASH_ITEMS` commands by key, so the "/" menu and the toolbar can never drift.

**Tech Stack:** Electron renderer: React 18, TipTap 2.27 + tiptap-markdown 0.8.10, zustand 5, TanStack Query 5, Tailwind 4 tokens (`styles.css` `@theme inline`), Vitest 2 + jsdom + Testing Library. No backend change. No new npm dependency.

**Spec:** The "A7 design" section below is the spec for this slice (A7 is not in the original spec). Context: `docs/superpowers/specs/2026-10-09-confluence-editor-design.md` (A1 blocks, A4 focus mode, the A5 toolbar "✦" hook) and the merged plans `2026-10-09-a1-editor-blocks.md`, `2026-10-09-a3-page-history.md`, `2026-10-09-a4-focus-read-aloud.md`, `2026-10-09-b1-vault-write-path.md`.

---

## A7 design

The user tested a dev build and said "the jots editor looks exactly the same". A1–A4 added Confluence *features*. A7 changes the *page*: what you see when a jot or a note is open.

### Layout

```
┌─ toolbar (fixed, 40px, hairline below) ─────────────────────────────────────────┐
│ Normal text ▾ │ B  I  S  <> │ •  1.  ☐ │ 🔗  ▦ │ ＋ Insert ▾                   ↔  │
└─────────────────────────────────────────────────────────────────────────────────┘
                  (scrolls)
             work  ›  payments                                    ← breadcrumb, 12px ink-3
             Quarterly planning                                   ← title, 34px display, editable
             (Y) you    updated 3h ago            history   2 backlinks   ← byline, 12px ink-2

             Body text at 16px / 1.7, in a 44rem column (≈80 characters)…
             > [!info] panels, tables, diagrams (A1) render here.

──────────── backlinks (collapsed) ────────────  (outside the page; opens from the byline)
```

The jot tree stays on the left as the page tree. The docs-assist panel stays opt-in on the right. Nothing else is added.

### Decisions

1. **Page width is a global setting (`pageWidth: 'fixed' | 'full'`, default `'fixed'`), not per note.** A per-note width would have to live in frontmatter. B1's body save keeps the frontmatter bytes exactly and there is no frontmatter write path from the editor, so per-note width would need a new backend write. Each toggle would also make a history version (A3) and a changed file, and on synced notes it would be overwritten by the next sync. Width is a reading preference of the person at this screen, like theme and density, which are global settings too. The toggle sits at the right end of the toolbar (Confluence's place). Focus mode (A4) always uses the fixed measure: that is A4's "centred at a reading measure".
2. **The title is the body's first line.** Today a jot's title is `title_from_body()`: the first non-empty line with `#` stripped (`ghostbrain/api/repo/notes_manual.py`). A vault note's title is frontmatter `title`, else the file name (`ghostbrain/api/repo/note.py`). There is no rename or title-write path, and body saves never touch frontmatter (B1). So:
   - **Notes** (`titleRule: 'note'`): a leading ATX H1 (`# Title`) is the page title and is removed from the editor. With no H1, the title field shows the note's frontmatter title or file name. If the user changes it, a `# New title` line is written at the top of the body. The frontmatter is never touched.
   - **Jots** (`titleRule: 'jot'`, also used for `source: manual | chat-summary` notes opened in the viewer): a leading H1, or a plain first line followed by a blank line or the end of the body. That is the same line the jot list already shows. Lines that are list items, quotes, fences, images, tables, `#tags`, or that carry inline markup (`[[`, `](`, backticks, `**`, `__`) are never taken as a title.
   - The title line is kept **byte for byte** until the user edits the title. A body-only save never rewrites it. CRLF files keep CRLF.
   - Renaming changes the page title only. The file is not moved and links do not break: wikilinks target paths, not titles.
   - An empty title is never saved (Confluence requires one). Blur restores the last title. Line breaks pasted into the title become spaces. Enter saves and moves into the page.
   - The title saves on the same 1 s debounce as the body, and at once on blur or Enter.
3. **Breadcrumb = ancestors only** (the page itself is the title): `context › project` from frontmatter (or `20-contexts/<context>/…`), `inbox` for `00-inbox/…`, else up to three folder names with their `NN-` prefix stripped. It is plain text, because a context has no page to open.
4. **Byline:** an initial chip and author (`frontmatter.author`, else `you` for manual notes and jots, else the source name, such as `gmail`), `updated <relative>` (`updated` → `created` → `ingestedAt`), then **history** (A3's `NoteHistoryButton`, moved out of the top bar and the viewer header) and **N backlinks** (A2's count; it opens the backlinks panel and scrolls to it).
5. **Toolbar** (replaces `EditorToolbar.tsx`; there is still one toolbar): text style (Normal text, Heading 1–3) · bold, italic, strikethrough, inline code · bullet, numbered, task list · link, table · **+ Insert** · page width. Every tooltip shows the shortcut that TipTap really binds (a test proves each one): ⌘B, ⌘I, ⌘⇧S, ⌘E, ⌘⇧8/7/9, ⌘⌥0–3 (Ctrl on Windows).
   - **Underline is left out on purpose.** Markdown has no underline. The editor runs tiptap-markdown with `html: false`, so a `<u>` mark would be silently dropped on the next save. A button that loses formatting is worse than none. Flag this to the user.
   - **Link has no shortcut**, because ⌘K is the Today search. The link editor is an inline form (Electron has no `window.prompt`). It accepts `http(s):` and `mailto:`. A bare `example.com` becomes `https://example.com`. Any other scheme (`javascript:`, `file:`, `data:`) is refused with a message.
   - **Insert menu**, in this order: Info, Note, Success, Warning, Error and Tip panels, Expand, Status, Table of contents, Mermaid diagram, Image (file picker), Photo (webcam), Table, Divider, Code block, Quote, Template (only when C1's `template` slash item exists), Ask AI (only when an `onAssist` handler is passed; A5 will pass it, and its plan already names this `EditorToolbar` prop). Every block row runs the A1 `SLASH_ITEMS` command with the same key. A1 has no success or error panel item, so A7 adds `success` and `error` to `SLASH_ITEMS` (A1's `CALLOUT_KINDS` and CSS already support both).
6. **Focus mode (A4):** the toolbar stays hidden, as A4 already does (shortcuts and "/" still work), and so do the breadcrumb and byline. The title stays. A4's `FocusBar` is the only chrome.
7. **Calmer chrome:** the backlinks panel starts collapsed and opens from the byline. The jots top bar loses its history button (now in the byline). The note viewer header loses its file title and path (now the page title and breadcrumb). The jots footer drops its context pill (now the breadcrumb).
8. **Visual direction.** The page is a document, not a card: no border, no shadow, `bg-paper`, centred. The one bold element is the title: Google Sans Flex at 34px, weight 640, tracking −0.025em, optical size 48. Everything around it is quiet. The breadcrumb is 12px `ink-3` with chevrons (no middle dots). The byline is 12px `ink-2`. Toolbar icons are 14px `ink-2`; active is `bg-fog text-ink-0`. Groups are separated by 1px `hairline-2` rules. The Insert trigger is the only labelled button. Body text is 16px / 1.7 in a 44rem column, and body headings step down from the title (26/21/18/16). Only design tokens are used, so light and dark themes both work.

---

## Global Constraints

- **A7 builds on a branch that contains A1** (`feat/a1-editor-blocks`, tip `6e8fb2da`, which is behind main). Merge A1 into main first, then branch `feat/a7-confluence-page` from main. Never branch from the A1 worktree as it is, because it lacks A2–A4 and B1. The pre-flight below checks for A1 by file, not by commit (a squash merge changes hashes).
- Main already has A2, A3, A4, B1, the hardening batch and the read-aloud voice fix. B2 and A5 are **not** merged. Do not reference `attributeNext`, `InlineAssistPopover` or `inlineAssist` props.
- `A7` below means the absolute path of the A7 worktree. Every command starts with `cd "$A7/desktop" && …` or `cd "$A7" && …`.
- No backend or Python change. No new npm dependency. No frontmatter writes. Every save goes through `GuardedNoteEditor` → `useGuardedSave` (B1). Never call `send` or the API directly from page components.
- The Insert menu must run A1's `SLASH_ITEMS[*].run`. It never re-implements a block insert.
- Keep the `EditorToolbar` export name and file path (A5's plan edits that element and adds `onAssist?: () => void`). The `onPhoto` prop goes away: Photo runs the `photo` slash item, which emits `gb:slash:photo`, and `RichMarkdownEditor` already listens for that.
- Accessible names already used by tests stay the same: toolbar button `bold`, viewer/top-bar button `history`, `focus mode (⌘ .)`, `exit focus mode`, the `src`/`rich` toggles and `copy formatted`.
- UI copy: icon-button `aria-label`s are lowercase (the app's voice: `bold`, `history`). Menu rows use sentence case, matching A1's slash titles (`Info panel`). The title placeholder is `Untitled`. No middle-dot separators in new chrome.
- Colours, fonts and radii come only from the design tokens (`text-ink-*`, `bg-paper`/`bg-vellum`/`bg-fog`, `border-hairline*`, `font-display`, `shadow-float`, CSS `var(--…)`). No hex colours, so light and dark themes both work.
- Never use real people's or employer names in code, tests, fixtures or docs.
- Desktop gates, run from `desktop/`: `npm run typecheck` (`tsc -b`; `tsc --noEmit` is a no-op here), `npx vitest run`, `npm run lint` (`--max-warnings 0`). Windows release builds rerun the desktop tests, so shortcut-label tests either pass `mac` explicitly or rely on the test setup's `platform: 'darwin'` stub. Never assert OS path separators.
- Commits end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Esc inside the Insert/text-style menu, the link form or a half-typed title while the note viewer is open.** It must close that menu or revert that title, without closing the viewer and without leaving focus mode. NoteView and A4 both skip a `defaultPrevented` Esc. Pinned in Task 5 (`Esc closes a menu and is consumed…`, `link: Esc closes the form and is consumed`) and Task 7 (`Esc with an unsaved title reverts it and is consumed…`).
2. **Typing in the body and renaming the title within one 1 s debounce window.** The file must end up with both changes, and the title line must never be lost or duplicated. Pinned in Task 7 (`a title rename and body typing in the same debounce window both land`).
3. **Files the split must not disturb:** CRLF line endings, no trailing newline, a one-line jot that is all title, an H1 directly followed by text, leading blank lines. A body-only save must keep the title line's bytes. Pinned in Task 2 (`round-trips byte for byte` table).
4. **Remounts with a new body:** history restore, "keep theirs" and the extract-photo result. The title must be re-read from the new body and never duplicated into the editor. Pinned in Task 7 (`a history restore re-reads the title…`, `reload adopts an outside write and re-splits it`).
5. **A `javascript:`, `file:` or `data:` address typed into the link form.** It must be refused with a message and leave no link mark. Pinned in Task 4 (`normalizeLinkHref` table) and Task 5 (`link: refuses script addresses`).

---

## File Structure

| File | Responsibility |
|---|---|
| `desktop/src/shared/types.ts` | `PageWidth` type and `Settings.pageWidth` |
| `desktop/src/shared/settings-schema.ts` | `pageWidth: z.enum(['fixed', 'full'])` |
| `desktop/src/main/settings.ts`, `desktop/src/main/demo/fixtures.ts`, `desktop/src/renderer/stores/settings.ts`, `desktop/src/renderer/test/setup.ts` | default `'fixed'` |
| `desktop/src/renderer/lib/editor/page-title.ts` (new) | split, join, retitle, sanitize: the pure title model |
| `desktop/src/renderer/lib/page-meta.ts` (new) | breadcrumb, author, updated and title-rule derivation from path + frontmatter |
| `desktop/src/renderer/components/page/PageByline.tsx` (new) | author chip, updated, history button, backlink count |
| `desktop/src/renderer/components/BacklinksPanel.tsx` | optional controlled `open` / `onOpenChange` |
| `desktop/src/renderer/lib/editor/toolbar-actions.ts` (new) | mark, list and text-style actions, shortcut labels, link normalise/apply |
| `desktop/src/renderer/lib/editor/insert-menu.ts` (new) | Insert rows (from `SLASH_ITEMS`, feature-checked) and `runInsert` |
| `desktop/src/renderer/lib/editor/slash.ts` | adds `success` and `error` panel items |
| `desktop/src/renderer/components/editor-toolbar/ToolbarMenu.tsx` (new) | dropdown button + menu (keyboard, Esc, outside click) |
| `desktop/src/renderer/components/editor-toolbar/LinkEditor.tsx` (new) | link button + inline address form |
| `desktop/src/renderer/components/EditorToolbar.tsx` | rewritten: the Confluence toolbar |
| `desktop/src/renderer/components/RichMarkdownEditor.tsx` | page canvas, `pageHeader` slot, image picker wiring |
| `desktop/src/renderer/styles.css` | `.gb-page*` rules; replaces A4's `.ProseMirror` focus rule |
| `desktop/src/renderer/components/page/PageTitle.tsx` (new) | the editable title textarea |
| `desktop/src/renderer/components/page/PageHeader.tsx` (new) | breadcrumb + title + byline arrangement (focus aware) |
| `desktop/src/renderer/components/GuardedNoteEditor.tsx` | `page` prop, title split/join, `GuardHandle.reload` |
| `desktop/src/renderer/screens/jots.tsx`, `desktop/src/renderer/components/NoteView.tsx` | pass `page`, move history, collapse backlinks, slimmer chrome |
| Tests | `settings-schema.test.ts`, `settings.test.ts`, `page-title.test.ts`, `page-meta.test.ts`, `PageByline.test.tsx`, `BacklinksPanel-controlled.test.tsx`, `toolbar-actions.test.ts`, `insert-menu.test.ts`, `slash.test.ts`, `EditorToolbar.test.tsx`, `RichMarkdownEditor-page.test.tsx`, `GuardedNoteEditor-page.test.tsx`, `jots.test.tsx`, `NoteView.test.tsx` |

## Pre-flight (before Task 1)

- [ ] **Confirm the branch contains A1 and main's A2–A4/B1**

Run:
```bash
cd "$A7" && git branch --show-current \
  && test -f desktop/src/renderer/components/TableToolbar.tsx \
  && grep -q "key: 'toc'" desktop/src/renderer/lib/editor/slash.ts \
  && test -f desktop/src/renderer/__tests__/helpers/editor.ts \
  && test -f desktop/src/renderer/components/FocusBar.tsx \
  && test -f desktop/src/renderer/components/HistoryDrawer.tsx \
  && test -f desktop/src/renderer/components/GuardedNoteEditor.tsx \
  && echo "A1 + main OK"
```
Expected: `feat/a7-confluence-page` then `A1 + main OK`. If any check fails, stop: A1 is not merged into this branch.

- [ ] **Baseline gates are green**

Run: `cd "$A7/desktop" && npm run typecheck && npx vitest run && npm run lint`
Expected: all PASS. Record any pre-existing failure before changing anything.

---

### Task 1: `pageWidth` setting

**Files:**
- Modify: `desktop/src/shared/types.ts`, `desktop/src/shared/settings-schema.ts`, `desktop/src/main/settings.ts`, `desktop/src/main/demo/fixtures.ts`, `desktop/src/renderer/stores/settings.ts`, `desktop/src/renderer/test/setup.ts`
- Test: `desktop/src/main/__tests__/settings-schema.test.ts`, `desktop/src/main/settings.test.ts`

**Interfaces:**
- Consumes: A4's settings pattern (`focusMode`, `readAloudVoice`, `readAloudRate`).
- Produces: `export type PageWidth = 'fixed' | 'full'` in `shared/types.ts`, `Settings.pageWidth: PageWidth` (default `'fixed'`), and `useSettings((s) => s.pageWidth)` / `useSettings.getState().set('pageWidth', v)` in the renderer.

- [ ] **Step 1: Write the failing tests**

Append to `desktop/src/main/__tests__/settings-schema.test.ts`:

```ts
describe('settings schema — page width (A7)', () => {
  it('pageWidth is fixed or full', () => {
    expect(settingsSchema.shape.pageWidth.safeParse('fixed').success).toBe(true);
    expect(settingsSchema.shape.pageWidth.safeParse('full').success).toBe(true);
    expect(settingsSchema.shape.pageWidth.safeParse('wide').success).toBe(false);
    expect(settingsSchema.shape.pageWidth.safeParse(true).success).toBe(false);
  });
});
```

Append inside `describe('settings store', …)` in `desktop/src/main/settings.test.ts`:

```ts
  it('defaults pageWidth to fixed, also for an older config.json without it', async () => {
    const { writeFileSync } = await import('node:fs');
    writeFileSync(join(workDir, 'config.json'), JSON.stringify({ version: 1, theme: 'light' }));
    const { getAll } = await import('./settings');
    expect(getAll().pageWidth).toBe('fixed');
  });
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd "$A7/desktop" && npx vitest run src/main/__tests__/settings-schema.test.ts src/main/settings.test.ts`
Expected: FAIL. `settingsSchema.shape.pageWidth` is undefined (TypeError), and `getAll().pageWidth` is `undefined`.

- [ ] **Step 3: Implement**

`desktop/src/shared/types.ts`: next to the other setting types (after `export type FolderStructure = …`) add:

```ts
/** A7 page canvas width: a reading measure or the editor's full width. */
export type PageWidth = 'fixed' | 'full';
```

In `interface Settings`, right after `readAloudRate: number;`, add:

```ts
  /** A7 page width (toolbar toggle). Global: a reading preference, not page content. */
  pageWidth: PageWidth;
```

`desktop/src/shared/settings-schema.ts`, right after `readAloudRate: z.number().min(0.5).max(2),`:

```ts
  // Page (A7): fixed reading measure or full editor width.
  pageWidth: z.enum(['fixed', 'full']),
```

`desktop/src/main/settings.ts` `DEFAULT_SETTINGS`, after `readAloudRate: 1,`:

```ts
  pageWidth: 'fixed',
```

`desktop/src/main/demo/fixtures.ts` `DEMO_SETTINGS`, after `readAloudRate: 1,`:

```ts
  pageWidth: 'fixed' as const,
```

`desktop/src/renderer/stores/settings.ts` and `desktop/src/renderer/test/setup.ts` (`defaultSettings`), after `readAloudRate: 1,`:

```ts
  pageWidth: 'fixed',
```

- [ ] **Step 4: Run the tests and the typecheck**

Run: `cd "$A7/desktop" && npx vitest run src/main/__tests__/settings-schema.test.ts src/main/settings.test.ts && npm run typecheck`
Expected: PASS. The typecheck catches any `Settings` literal that misses the key.

- [ ] **Step 5: Commit**

```bash
cd "$A7" && git add desktop/src/shared/types.ts desktop/src/shared/settings-schema.ts desktop/src/main/settings.ts desktop/src/main/demo/fixtures.ts desktop/src/renderer/stores/settings.ts desktop/src/renderer/test/setup.ts desktop/src/main/__tests__/settings-schema.test.ts desktop/src/main/settings.test.ts
git commit -m "feat(settings): global pageWidth (fixed or full) for the page canvas (A7)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Page title model

**Files:**
- Create: `desktop/src/renderer/lib/editor/page-title.ts`
- Test: `desktop/src/renderer/__tests__/page-title.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `type TitleRule = 'jot' | 'note'`
  - `interface PageTitleSplit { title: string; kind: 'h1' | 'plain' | null; head: string; rest: string; eol: '\n' | '\r\n' }`. `kind === null` means the body owns no title (`title === ''`, `head === ''`, `rest === body`).
  - `splitPageTitle(body: string, rule: TitleRule): PageTitleSplit`
  - `joinPageTitle(split: PageTitleSplit, rest: string): string`. When `rest` is unchanged it returns the original body byte for byte.
  - `retitlePage(split: PageTitleSplit, raw: string): PageTitleSplit | null`. Returns `null` when the sanitised title is empty or equal to `split.title`.
  - `sanitizePageTitle(raw: string): string`: collapses whitespace (line breaks included), trims, and caps at 200 characters.

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/page-title.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import {
  joinPageTitle,
  retitlePage,
  sanitizePageTitle,
  splitPageTitle,
} from '../lib/editor/page-title';

describe('splitPageTitle', () => {
  it('takes a leading H1 as the title for notes and jots', () => {
    for (const rule of ['note', 'jot'] as const) {
      const s = splitPageTitle('# Plan\n\nbody text', rule);
      expect(s).toMatchObject({ title: 'Plan', kind: 'h1', head: '# Plan\n\n', rest: 'body text' });
    }
  });

  it('a note without an H1 owns no title', () => {
    expect(splitPageTitle('hand-written', 'note')).toMatchObject({ title: '', kind: null, head: '', rest: 'hand-written' });
  });

  it('a jot owns a plain first line followed by a blank line or the end', () => {
    expect(splitPageTitle('first jot\n\nfull body here', 'jot')).toMatchObject({
      title: 'first jot', kind: 'plain', head: 'first jot\n\n', rest: 'full body here',
    });
    expect(splitPageTitle('pending content here', 'jot')).toMatchObject({
      title: 'pending content here', kind: 'plain', rest: '',
    });
  });

  it('a jot whose first line runs on into a paragraph owns no title', () => {
    expect(splitPageTitle('line one\nline two', 'jot').kind).toBeNull();
  });

  it.each([
    '- item\n\nx',
    '1. item\n\nx',
    '#tag line\n\nx',
    '## Second level\n\nx',
    '> [!info]\n> x',
    '```js\nconst a = 1;\n```',
    '![](90-meta/assets/a.png)\n\nx',
    '| a | b |\n\nx',
    '[[a note]] is related\n\nx',
    'see [the docs](https://a.example)\n\nx',
    '**bold** opener\n\nx',
    'run `make` first\n\nx',
    '---\n\nx',
    'x'.repeat(121) + '\n\nbody',
  ])('a jot never takes %j as its title', (body) => {
    expect(splitPageTitle(body, 'jot').kind).toBeNull();
  });

  it('strips an ATX closing sequence and unescapes a trailing \\#', () => {
    expect(splitPageTitle('# Title ##\n\nx', 'note').title).toBe('Title');
    expect(splitPageTitle('# Issue \\#\n\nx', 'note').title).toBe('Issue #');
  });

  it('an empty H1 owns no title', () => {
    expect(splitPageTitle('# \n\nx', 'note').kind).toBeNull();
    expect(splitPageTitle('#\n\nx', 'note').kind).toBeNull();
  });
});

describe('joinPageTitle round-trips byte for byte', () => {
  it.each([
    ['h1 + blank + body', '# Plan\n\nbody text', 'note'],
    ['h1 straight into text', '# T\nbody', 'note'],
    ['crlf', '# T\r\n\r\nbody\r\n', 'note'],
    ['leading blank lines', '\n\n# T\n\nx', 'note'],
    ['no-title note', 'hand-written', 'note'],
    ['jot plain title', 'first jot\n\nfull body here', 'jot'],
    ['title-only jot', 'pending content here', 'jot'],
    ['new jot default', 'new jot\n\n', 'jot'],
    ['h1 only, trailing newline', '# Only\n', 'note'],
  ] as const)('%s', (_name, body, rule) => {
    const s = splitPageTitle(body, rule);
    expect(joinPageTitle(s, s.rest)).toBe(body);
  });

  it('puts a blank line between a title line at EOF and new body text', () => {
    const plain = splitPageTitle('pending content here', 'jot');
    expect(joinPageTitle(plain, 'more')).toBe('pending content here\n\nmore');
    const h1 = splitPageTitle('# Only', 'note');
    expect(joinPageTitle(h1, 'more')).toBe('# Only\n\nmore');
  });

  it('keeps the title line when the body is emptied', () => {
    const s = splitPageTitle('# Plan\n\nbody', 'note');
    expect(joinPageTitle(s, '')).toBe('# Plan\n\n');
  });
});

describe('retitlePage', () => {
  it('rewrites an H1 title and keeps everything around it', () => {
    const s = splitPageTitle('# Plan\n\nbody', 'note');
    expect(joinPageTitle(retitlePage(s, 'Launch plan')!, 'body')).toBe('# Launch plan\n\nbody');
  });

  it('keeps a plain jot title plain', () => {
    const s = splitPageTitle('first jot\n\nx', 'jot');
    const next = retitlePage(s, 'Sprint retro')!;
    expect(next.kind).toBe('plain');
    expect(joinPageTitle(next, 'x')).toBe('Sprint retro\n\nx');
  });

  it('promotes a plain title to an H1 when the new text would read as markdown', () => {
    const s = splitPageTitle('first jot\n\nx', 'jot');
    expect(joinPageTitle(retitlePage(s, '- not a list')!, 'x')).toBe('# - not a list\n\nx');
  });

  it('writes a new H1 above a body that owned no title', () => {
    const s = splitPageTitle('hand-written', 'note');
    expect(joinPageTitle(retitlePage(s, 'Spec')!, 'hand-written')).toBe('# Spec\n\nhand-written');
  });

  it('keeps CRLF', () => {
    const s = splitPageTitle('# T\r\n\r\nbody', 'note');
    expect(joinPageTitle(retitlePage(s, 'U')!, 'body')).toBe('# U\r\n\r\nbody');
  });

  it('escapes a trailing # so it is not read as a closing sequence', () => {
    const s = splitPageTitle('# Plan\n\nx', 'note');
    const next = retitlePage(s, 'Issue #')!;
    expect(joinPageTitle(next, 'x')).toBe('# Issue \\#\n\nx');
    expect(splitPageTitle(joinPageTitle(next, 'x'), 'note').title).toBe('Issue #');
  });

  it('returns null for an unchanged, blank or whitespace-only title', () => {
    const s = splitPageTitle('# Plan\n\nx', 'note');
    expect(retitlePage(s, 'Plan')).toBeNull();
    expect(retitlePage(s, '  Plan  ')).toBeNull();
    expect(retitlePage(s, '   ')).toBeNull();
  });
});

describe('sanitizePageTitle', () => {
  it('collapses whitespace and line breaks, trims, caps at 200', () => {
    expect(sanitizePageTitle('  A \n\t B  ')).toBe('A B');
    expect(sanitizePageTitle('x'.repeat(250))).toHaveLength(200);
  });
});
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/page-title.test.ts`
Expected: FAIL. `Failed to resolve import "../lib/editor/page-title"`.

- [ ] **Step 3: Implement**

Create `desktop/src/renderer/lib/editor/page-title.ts`:

```ts
/**
 * A7 page title. The title is a line of the note body, never frontmatter:
 * B1's body save keeps frontmatter bytes exactly and there is no title
 * write path.
 *  - 'note': a leading ATX H1 (`# Title`) is the title.
 *  - 'jot':  the same, or a plain first line followed by a blank line or the
 *            end of the body (the line title_from_body() lists for jots).
 * `head` holds the title line and its surrounding blank lines byte for byte,
 * so a save that only changed the body never rewrites the title line.
 */
export type TitleRule = 'jot' | 'note';

export interface PageTitleSplit {
  /** Display title; '' when the body owns none. */
  title: string;
  /** How the body holds the title; null when it holds none. */
  kind: 'h1' | 'plain' | null;
  /** Raw text before `rest`: leading blank lines, the title line, its line
   * ending and the blank lines after it. '' when kind is null. */
  head: string;
  /** What the editor shows and edits. */
  rest: string;
  /** Line ending used when a head is rebuilt. */
  eol: '\n' | '\r\n';
}

const BLANK_RUN = /^(?:[ \t]*\r?\n)*/;
const H1_RE = /^ {0,3}# +(.*?)(?: +#+)? *$/;
/** First-line shapes that are markdown blocks, not a title. */
const NOT_PLAIN = /^(?:#|[-*+](?:\s|$)|\d{1,9}[.)](?:\s|$)|>|`{3}|~{3}|!\[|\||<|(?:[-*_][ \t]*){3,}$|=+$)/;
/** Inline markup a plain textarea title cannot show. */
const INLINE_MARKUP = /\[\[|\]\(|`|\*\*|__/;
const PLAIN_MAX = 120;
const TITLE_MAX = 200;

function isPlainTitle(text: string): boolean {
  return (
    text !== '' && text.length <= PLAIN_MAX && !NOT_PLAIN.test(text) && !INLINE_MARKUP.test(text)
  );
}

const unescapeTitle = (s: string): string => s.replace(/\\(#+)$/, '$1');
/** A trailing ` #…` is an ATX closing sequence: escape it. */
const escapeH1 = (s: string): string => s.replace(/( )(#+)$/, '$1\\$2');

export function sanitizePageTitle(raw: string): string {
  return raw.replace(/\s+/g, ' ').trim().slice(0, TITLE_MAX);
}

export function splitPageTitle(body: string, rule: TitleRule): PageTitleSplit {
  const eol: '\n' | '\r\n' = body.includes('\r\n') ? '\r\n' : '\n';
  const none: PageTitleSplit = { title: '', kind: null, head: '', rest: body, eol };

  const lead = BLANK_RUN.exec(body)![0];
  const afterLead = body.slice(lead.length);
  const nl = afterLead.search(/\r?\n/);
  const line = nl === -1 ? afterLead : afterLead.slice(0, nl);
  const lineEol = nl === -1 ? '' : afterLead.startsWith('\r\n', nl) ? '\r\n' : '\n';
  const tail = afterLead.slice(line.length + lineEol.length);
  const blanks = BLANK_RUN.exec(tail)![0];
  const rest = tail.slice(blanks.length);
  const head = lead + line + lineEol + blanks;

  const h1 = H1_RE.exec(line);
  if (h1) {
    const title = unescapeTitle(h1[1]!.trim());
    return title === '' ? none : { title, kind: 'h1', head, rest, eol };
  }
  if (rule !== 'jot') return none;
  const text = line.trim();
  const endsBlock = lineEol === '' || blanks !== '' || rest.trim() === '';
  if (!endsBlock || !isPlainTitle(text)) return none;
  return { title: text, kind: 'plain', head, rest, eol };
}

export function joinPageTitle(split: PageTitleSplit, rest: string): string {
  if (split.kind === null) return rest;
  const { head, eol } = split;
  if (rest.trim() === '') return head;
  if (/\r?\n[ \t]*\r?\n$/.test(head)) return head + rest;
  // An H1 ends at its line ending; a plain line needs a blank line or it
  // merges into the first paragraph.
  if (split.kind === 'h1' && /\n$/.test(head)) return head + rest;
  return head.replace(/[ \t]*(?:\r?\n)?$/, '') + eol + eol + rest;
}

export function retitlePage(split: PageTitleSplit, raw: string): PageTitleSplit | null {
  const title = sanitizePageTitle(raw);
  if (title === '' || title === split.title) return null;
  const { eol } = split;
  if (split.kind === null) {
    return { title, kind: 'h1', head: `# ${escapeH1(title)}${eol}${eol}`, rest: split.rest, eol };
  }
  // Swap only the title line; keep the blank lines before and after it.
  const m = /^((?:[ \t]*\r?\n)*)([^\r\n]*)([\s\S]*)$/.exec(split.head)!;
  const plain = split.kind === 'plain' && isPlainTitle(title);
  const line = plain ? title : `# ${escapeH1(title)}`;
  return { title, kind: plain ? 'plain' : 'h1', head: m[1]! + line + m[3]!, rest: split.rest, eol };
}
```

- [ ] **Step 4: Run the tests**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/page-title.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$A7" && git add desktop/src/renderer/lib/editor/page-title.ts desktop/src/renderer/__tests__/page-title.test.ts
git commit -m "feat(editor): page title model that splits the title line off the body byte-exactly (A7)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Page metadata, byline and controllable backlinks

**Files:**
- Create: `desktop/src/renderer/lib/page-meta.ts`, `desktop/src/renderer/components/page/PageByline.tsx`
- Modify: `desktop/src/renderer/components/BacklinksPanel.tsx`
- Test: `desktop/src/renderer/__tests__/page-meta.test.ts`, `desktop/src/renderer/__tests__/PageByline.test.tsx`, `desktop/src/renderer/__tests__/BacklinksPanel-controlled.test.tsx`

**Interfaces:**
- Consumes: `TitleRule` (Task 2), A2's `useBacklinks(path)` (`{ items: Backlink[]; indexing: boolean }`), A3's `NoteHistoryButton({ path, guardRef })`, `formatRelativeTime(iso)` from `lib/format.ts`, and `GuardHandle` (type only) from `components/GuardedNoteEditor`.
- Produces:
  - `pageBreadcrumb(path: string, fm: Record<string, unknown> | null | undefined): string[]`
  - `pageAuthor(fm): string`, `pageUpdated(fm): string | null`, `titleRuleFor(fm): TitleRule`
  - `PageByline(props: { author: string; updated: string | null; path: string; guardRef: React.MutableRefObject<GuardHandle | null>; onShowBacklinks: () => void })`, rendered as `data-testid="page-byline"`. The backlinks button reads `N backlinks` (`1 backlink` for one) and is only shown when the count is settled (not indexing).
  - `BacklinksPanel` props gain `open?: boolean; onOpenChange?: (open: boolean) => void`. Without them it behaves as today (uncontrolled, open).

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/page-meta.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { pageAuthor, pageBreadcrumb, pageUpdated, titleRuleFor } from '../lib/page-meta';

describe('pageBreadcrumb', () => {
  it.each([
    ['20-contexts/work/notes/x.md', { context: 'work', project: 'payments' }, ['work', 'payments']],
    ['20-contexts/work/notes/x.md', {}, ['work']],
    ['00-inbox/raw/manual/x.md', { context: null }, ['inbox']],
    ['00-inbox/raw/manual/x.md', { context: 'personal' }, ['personal']],
    ['10-daily/2026/10/2026-10-10.md', {}, ['daily', '2026', '10']],
    ['x.md', undefined, []],
  ] as const)('%s → %j', (path, fm, expected) => {
    expect(pageBreadcrumb(path, fm as Record<string, unknown> | undefined)).toEqual(expected);
  });
});

describe('pageAuthor', () => {
  it.each([
    [{ author: 'ops-bot' }, 'ops-bot'],
    [{ source: 'manual' }, 'you'],
    [{ source: 'chat-summary' }, 'you'],
    [{}, 'you'],
    [undefined, 'you'],
    [{ source: 'gmail' }, 'gmail'],
    [{ author: ['a', 'b'], source: 'slack' }, 'slack'],
  ] as const)('%j → %s', (fm, expected) => {
    expect(pageAuthor(fm as Record<string, unknown> | undefined)).toBe(expected);
  });
});

describe('pageUpdated', () => {
  it('prefers updated, then created, then ingestedAt', () => {
    expect(pageUpdated({ updated: '2026-10-10T08:00:00Z', created: '2026-10-01T08:00:00Z' })).toBe('2026-10-10T08:00:00Z');
    expect(pageUpdated({ created: '2026-10-01T08:00:00Z' })).toBe('2026-10-01T08:00:00Z');
    expect(pageUpdated({ ingestedAt: '2026-09-01T08:00:00Z' })).toBe('2026-09-01T08:00:00Z');
    expect(pageUpdated({})).toBeNull();
    expect(pageUpdated(undefined)).toBeNull();
  });
});

describe('titleRuleFor', () => {
  it('jots and chat summaries use the jot rule; everything else the note rule', () => {
    expect(titleRuleFor({ source: 'manual' })).toBe('jot');
    expect(titleRuleFor({ source: 'chat-summary' })).toBe('jot');
    expect(titleRuleFor({ source: 'gmail' })).toBe('note');
    expect(titleRuleFor(undefined)).toBe('note');
  });
});
```

Create `desktop/src/renderer/__tests__/PageByline.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PageByline } from '../components/page/PageByline';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  window.gb = { ...window.gb, api: { request: apiRequest } };
});

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const twoLinks = {
  ok: true,
  data: {
    items: [
      { path: 'a.md', title: 'A', context: null, snippet: '' },
      { path: 'b.md', title: 'B', context: null, snippet: '' },
    ],
    indexing: false,
  },
};

describe('PageByline', () => {
  it('shows the author, relative update time, history and backlink count', async () => {
    apiRequest.mockResolvedValue(twoLinks);
    const onShow = vi.fn();
    const updated = new Date(Date.now() - 3 * 3_600_000).toISOString();
    render(
      withQuery(
        <PageByline author="you" updated={updated} path="n.md" guardRef={{ current: null }} onShowBacklinks={onShow} />,
      ),
    );
    expect(screen.getByText('you')).toBeInTheDocument();
    expect(screen.getByText('updated 3h ago')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'history' })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: '2 backlinks' }));
    expect(onShow).toHaveBeenCalledOnce();
  });

  it('says "1 backlink" for one', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { items: [twoLinks.data.items[0]], indexing: false } });
    render(withQuery(<PageByline author="you" updated={null} path="n.md" guardRef={{ current: null }} onShowBacklinks={() => {}} />));
    expect(await screen.findByRole('button', { name: '1 backlink' })).toBeInTheDocument();
  });

  it('hides the count while the link index is building, and the time when unknown', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { items: [], indexing: true } });
    render(withQuery(<PageByline author="you" updated={null} path="n.md" guardRef={{ current: null }} onShowBacklinks={() => {}} />));
    await waitFor(() => expect(apiRequest).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /backlink/ })).toBeNull();
    expect(screen.queryByText(/updated/)).toBeNull();
  });
});
```

Create `desktop/src/renderer/__tests__/BacklinksPanel-controlled.test.tsx`:

```tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BacklinksPanel } from '../components/BacklinksPanel';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  apiRequest.mockResolvedValue({
    ok: true,
    data: { items: [{ path: 's.md', title: 'Standup', context: 'work', snippet: '' }], indexing: false },
  });
  window.gb = { ...window.gb, api: { request: apiRequest } };
});

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('BacklinksPanel controlled (A7)', () => {
  it('stays closed when the parent says so and reports toggles', async () => {
    const onOpenChange = vi.fn();
    render(withQuery(<BacklinksPanel path="n.md" onOpen={() => {}} open={false} onOpenChange={onOpenChange} />));
    const header = await screen.findByRole('button', { name: /backlinks/ });
    expect(header).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Standup')).toBeNull();
    fireEvent.click(header);
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });

  it('shows the list when the parent opens it', async () => {
    render(withQuery(<BacklinksPanel path="n.md" onOpen={() => {}} open onOpenChange={() => {}} />));
    expect(await screen.findByText('Standup')).toBeInTheDocument();
  });

  it('without the props it is open by default, as before', async () => {
    render(withQuery(<BacklinksPanel path="n.md" onOpen={() => {}} />));
    expect(await screen.findByText('Standup')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/page-meta.test.ts src/renderer/__tests__/PageByline.test.tsx src/renderer/__tests__/BacklinksPanel-controlled.test.tsx`
Expected: FAIL. `page-meta` and `PageByline` cannot be resolved, and the controlled panel test finds `aria-expanded="true"`.

- [ ] **Step 3: Implement**

Create `desktop/src/renderer/lib/page-meta.ts`:

```ts
import type { TitleRule } from './editor/page-title';

type Frontmatter = Record<string, unknown> | null | undefined;

const text = (v: unknown): string | null =>
  typeof v === 'string' && v.trim() !== '' ? v.trim() : null;

/** Frontmatter `source` values written by the user (jots, chat summaries). */
const OWN_SOURCES = new Set(['manual', 'chat-summary']);

/** Ancestors shown above the page title (the page itself is the title). */
export function pageBreadcrumb(path: string, fm: Frontmatter): string[] {
  const dirs = path.split('/').filter((s) => s !== '' && s !== '.');
  dirs.pop();
  const context = text(fm?.context) ?? (dirs[0] === '20-contexts' ? (dirs[1] ?? null) : null);
  if (context) {
    const project = text(fm?.project);
    return project ? [context, project] : [context];
  }
  if (dirs[0] === '00-inbox') return ['inbox'];
  return dirs
    .map((d) => d.replace(/^\d{2}-/, ''))
    .filter((d) => d !== '')
    .slice(-3);
}

export function pageAuthor(fm: Frontmatter): string {
  const author = text(fm?.author);
  if (author) return author;
  const source = text(fm?.source);
  return source === null || OWN_SOURCES.has(source) ? 'you' : source;
}

export function pageUpdated(fm: Frontmatter): string | null {
  return text(fm?.updated) ?? text(fm?.created) ?? text(fm?.ingestedAt);
}

/** Jots (and chat summaries) list their first line as the title. */
export function titleRuleFor(fm: Frontmatter): TitleRule {
  const source = text(fm?.source);
  return source !== null && OWN_SOURCES.has(source) ? 'jot' : 'note';
}
```

Create `desktop/src/renderer/components/page/PageByline.tsx`:

```tsx
import { useBacklinks } from '../../lib/api/hooks';
import { formatRelativeTime } from '../../lib/format';
import { Btn } from '../Btn';
import type { GuardHandle } from '../GuardedNoteEditor';
import { Lucide } from '../Lucide';
import { NoteHistoryButton } from '../NoteHistory';

interface Props {
  author: string;
  /** ISO timestamp; null hides the "updated" item. */
  updated: string | null;
  /** Vault-relative path of the page (history + backlinks). */
  path: string;
  guardRef: React.MutableRefObject<GuardHandle | null>;
  /** Opens the backlinks panel and brings it into view. */
  onShowBacklinks: () => void;
}

/** Confluence-style byline under the page title (A7). */
export function PageByline({ author, updated, path, guardRef, onShowBacklinks }: Props) {
  const backlinks = useBacklinks(path);
  const items = backlinks.data?.items;
  const count =
    backlinks.isSuccess && backlinks.data?.indexing !== true && Array.isArray(items)
      ? items.length
      : null;

  return (
    <div
      data-testid="page-byline"
      className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-12 text-ink-2"
    >
      <span className="flex items-center gap-2">
        <span
          aria-hidden
          className="flex h-5 w-5 items-center justify-center rounded-pill bg-fog text-10 font-medium text-ink-1"
        >
          {author.charAt(0).toUpperCase()}
        </span>
        <span className="text-ink-1">{author}</span>
      </span>
      {updated && <span title={updated}>updated {formatRelativeTime(updated)}</span>}
      <span className="ml-auto flex items-center gap-1">
        <NoteHistoryButton key={path} path={path} guardRef={guardRef} />
        {count !== null && (
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="link-2" size={13} />}
            onClick={onShowBacklinks}
          >
            {count === 1 ? '1 backlink' : `${count} backlinks`}
          </Btn>
        )}
      </span>
    </div>
  );
}
```

`desktop/src/renderer/components/BacklinksPanel.tsx`: change the `Props` interface and the open state. Replace

```tsx
interface Props {
  /** Vault-relative `.md` path of the note being viewed. */
  path: string;
  onOpen: (path: string) => void;
}

export function BacklinksPanel({ path, onOpen }: Props) {
  const [open, setOpen] = useState(true);
```

with

```tsx
interface Props {
  /** Vault-relative `.md` path of the note being viewed. */
  path: string;
  onOpen: (path: string) => void;
  /** Controlled open state (A7 page byline). Omit both for the old behaviour. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function BacklinksPanel({ path, onOpen, open: openProp, onOpenChange }: Props) {
  const [ownOpen, setOwnOpen] = useState(true);
  const open = openProp ?? ownOpen;
  const setOpen = (next: boolean) => (onOpenChange ? onOpenChange(next) : setOwnOpen(next));
```

and change the header button's `onClick={() => setOpen((o) => !o)}` to `onClick={() => setOpen(!open)}`.

- [ ] **Step 4: Run the tests**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/page-meta.test.ts src/renderer/__tests__/PageByline.test.tsx src/renderer/__tests__/BacklinksPanel-controlled.test.tsx src/renderer/__tests__/BacklinksPanel.test.tsx && npm run typecheck`
Expected: PASS. The existing `BacklinksPanel.test.tsx` is unchanged and still passes.

- [ ] **Step 5: Commit**

```bash
cd "$A7" && git add desktop/src/renderer/lib/page-meta.ts desktop/src/renderer/components/page/PageByline.tsx desktop/src/renderer/components/BacklinksPanel.tsx desktop/src/renderer/__tests__/page-meta.test.ts desktop/src/renderer/__tests__/PageByline.test.tsx desktop/src/renderer/__tests__/BacklinksPanel-controlled.test.tsx
git commit -m "feat(page): breadcrumb/author/updated helpers, page byline and controllable backlinks (A7)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Toolbar actions and the Insert model

**Files:**
- Create: `desktop/src/renderer/lib/editor/toolbar-actions.ts`, `desktop/src/renderer/lib/editor/insert-menu.ts`
- Modify: `desktop/src/renderer/lib/editor/slash.ts`
- Test: `desktop/src/renderer/__tests__/toolbar-actions.test.ts`, `desktop/src/renderer/__tests__/insert-menu.test.ts`, `desktop/src/renderer/__tests__/slash.test.ts`

**Interfaces:**
- Consumes: A1's `SLASH_ITEMS: SlashItem[]` and `SlashItem { key; title; run(editor, range) }` (`lib/editor/slash.ts`), A1's `setCallout`, `isMac` (`lib/platform.ts`), and A1's test helpers `makeEditor(content, editable?)` / `markdownOf(editor)` (`__tests__/helpers/editor.ts`).
- Produces:
  - `interface ShortcutSpec { key: string; shift?: boolean; alt?: boolean }`, `shortcutText(s, mac = isMac): string` (`'⌘ ⇧ S'`, `'Ctrl Alt 2'`), and `withShortcut(label, s?, mac = isMac): string` (`'Bold (⌘ B)'`)
  - `interface ToolbarAction { id: string; label: string; icon: string; shortcut?: ShortcutSpec; run(editor): void; isActive(editor): boolean }`, `MARK_ACTIONS` (ids `bold`, `italic`, `strikethrough`, `code`) and `LIST_ACTIONS` (ids `bullet list`, `numbered list`, `task list`)
  - `interface TextStyle { id: 'paragraph' | 'h1' | 'h2' | 'h3'; label: string; shortcut: ShortcutSpec; run(editor): void; isActive(editor): boolean }`, `TEXT_STYLES`, and `currentTextStyle(editor): string`
  - `normalizeLinkHref(raw): { ok: true; href: string } | { ok: false; error: string }` and `applyLink(editor, href: string | null): void`
  - `interface InsertEntry { key: string; label: string; icon: string; kind: 'slash' | 'image' | 'assist' }`, `insertEntries(opts: { slashItems?: readonly SlashItem[]; canPickImage: boolean; canAssist: boolean }): InsertEntry[]`, and `runInsert(editor, key, slashItems = SLASH_ITEMS): boolean`
  - `SLASH_ITEMS` gains `success` ("Success panel") and `error` ("Error panel") after `warning`.

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/toolbar-actions.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import {
  LIST_ACTIONS,
  MARK_ACTIONS,
  TEXT_STYLES,
  currentTextStyle,
  normalizeLinkHref,
  shortcutText,
  withShortcut,
  type ShortcutSpec,
} from '../lib/editor/toolbar-actions';
import { makeEditor } from './helpers/editor';

/** TipTap key name for a spec, as its keymaps declare it. */
const keyName = (s: ShortcutSpec): string =>
  ['Mod', ...(s.shift ? ['Shift'] : []), ...(s.alt ? ['Alt'] : []), s.key].join('-');

describe('shortcut labels', () => {
  it('use ⌘ on macOS and Ctrl elsewhere', () => {
    expect(shortcutText({ key: 'b' }, true)).toBe('⌘ B');
    expect(shortcutText({ key: 'b' }, false)).toBe('Ctrl B');
    expect(shortcutText({ key: 's', shift: true }, true)).toBe('⌘ ⇧ S');
    expect(shortcutText({ key: '2', alt: true }, true)).toBe('⌘ ⌥ 2');
    expect(shortcutText({ key: '2', alt: true }, false)).toBe('Ctrl Alt 2');
    expect(withShortcut('Bold', { key: 'b' }, false)).toBe('Bold (Ctrl B)');
    expect(withShortcut('Link', undefined, true)).toBe('Link');
  });
});

describe('every tooltip shortcut is one the editor really binds', () => {
  it.each([...MARK_ACTIONS, ...LIST_ACTIONS].map((a) => [a.id, a] as const))('%s', (_id, a) => {
    const editor = makeEditor('word');
    editor.commands.selectAll();
    editor.commands.keyboardShortcut(keyName(a.shortcut!));
    expect(a.isActive(editor)).toBe(true);
    editor.destroy();
  });

  it.each(TEXT_STYLES.map((s) => [s.id, s] as const))('%s', (id, s) => {
    const editor = makeEditor(id === 'paragraph' ? '# word' : 'word');
    editor.commands.keyboardShortcut(keyName(s.shortcut));
    expect(s.isActive(editor)).toBe(true);
    editor.destroy();
  });
});

describe('text styles', () => {
  it('names the block under the cursor', () => {
    const cases: Array<[string, string]> = [
      ['# t', 'Heading 1'],
      ['### t', 'Heading 3'],
      ['#### t', 'Heading 4'],
      ['t', 'Normal text'],
    ];
    for (const [md, label] of cases) {
      const editor = makeEditor(md);
      expect(currentTextStyle(editor)).toBe(label);
      editor.destroy();
    }
  });
});

describe('normalizeLinkHref', () => {
  it.each([
    ['https://a.example/x', 'https://a.example/x'],
    ['HTTP://A.EXAMPLE', 'HTTP://A.EXAMPLE'],
    ['mailto:team@a.example', 'mailto:team@a.example'],
    ['example.com/path', 'https://example.com/path'],
    ['localhost:5173', 'https://localhost:5173'],
    ['  https://a.example  ', 'https://a.example'],
  ])('accepts %j', (raw, href) => {
    expect(normalizeLinkHref(raw)).toEqual({ ok: true, href });
  });

  it.each([
    ['javascript:alert(1)', 'Use an http, https or mailto link'],
    ['data:text/html,x', 'Use an http, https or mailto link'],
    ['file:///etc/hosts', 'Use an http, https or mailto link'],
    ['', 'Enter a link'],
    ['a b', 'Links cannot contain spaces'],
  ])('refuses %j', (raw, error) => {
    expect(normalizeLinkHref(raw)).toEqual({ ok: false, error });
  });
});
```

Create `desktop/src/renderer/__tests__/insert-menu.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest';
import { insertEntries, runInsert } from '../lib/editor/insert-menu';
import { SLASH_ITEMS, type SlashItem } from '../lib/editor/slash';
import { onGb } from '../lib/editor/events';
import { makeEditor, markdownOf } from './helpers/editor';

const BASE = [
  'info', 'note', 'success', 'warning', 'error', 'tip', 'expand', 'status', 'toc', 'diagram',
  'image', 'photo', 'table', 'divider', 'code', 'quote',
];
const hasTemplate = SLASH_ITEMS.some((i) => i.key === 'template');

describe('insertEntries', () => {
  it('lists the A1 blocks, the new panels and media in Confluence order', () => {
    const keys = insertEntries({ canPickImage: true, canAssist: false }).map((e) => e.key);
    expect(keys).toEqual(hasTemplate ? [...BASE, 'template'] : BASE);
  });

  it('offers Template only when the template slash item exists (C1)', () => {
    const withTemplate: SlashItem[] = [...SLASH_ITEMS.filter((i) => i.key !== 'template'), { key: 'template', title: 'Template', run: () => {} }];
    expect(insertEntries({ slashItems: withTemplate, canPickImage: true, canAssist: false }).at(-1)).toMatchObject({ key: 'template', label: 'Template', kind: 'slash' });
    const without = SLASH_ITEMS.filter((i) => i.key !== 'template');
    expect(insertEntries({ slashItems: without, canPickImage: true, canAssist: false }).map((e) => e.key)).not.toContain('template');
  });

  it('skips a block whose slash item is missing, and Image without a picker', () => {
    const noDiagram = SLASH_ITEMS.filter((i) => i.key !== 'diagram');
    const keys = insertEntries({ slashItems: noDiagram, canPickImage: false, canAssist: false }).map((e) => e.key);
    expect(keys).not.toContain('diagram');
    expect(keys).not.toContain('image');
  });

  it('adds Ask AI last only when an assist handler exists', () => {
    expect(insertEntries({ canPickImage: true, canAssist: true }).at(-1)).toEqual({ key: 'assist', label: 'Ask AI', icon: 'sparkles', kind: 'assist' });
    expect(insertEntries({ canPickImage: true, canAssist: false }).map((e) => e.key)).not.toContain('assist');
  });
});

describe('runInsert', () => {
  it.each([
    ['success', '> [!success]'],
    ['error', '> [!error]'],
    ['info', '> [!info]'],
    ['toc', '```toc\n```'],
  ])('%s runs the A1 command at the cursor', (key, md) => {
    const editor = makeEditor('');
    expect(runInsert(editor, key)).toBe(true);
    expect(markdownOf(editor)).toBe(md);
    editor.destroy();
  });

  it('status opens the lozenge editor at the cursor', () => {
    const editor = makeEditor('');
    const spy = vi.fn();
    onGb(editor, 'gb:status:edit', spy);
    runInsert(editor, 'status');
    expect(markdownOf(editor)).toBe('`status:To do/grey`');
    expect(spy).toHaveBeenCalledWith({ pos: 1 });
    editor.destroy();
  });

  it('refuses unknown keys and read-only editors', () => {
    const editor = makeEditor('word', false);
    expect(runInsert(editor, 'nope')).toBe(false);
    expect(runInsert(editor, 'info')).toBe(false);
    expect(markdownOf(editor)).toBe('word');
    editor.destroy();
  });
});
```

In `desktop/src/renderer/__tests__/slash.test.ts` (A1), inside `describe('A1 slash items', …)`, change the panel expectation and extend the table:

```ts
    expect(filterSlashItems('panel').map((i) => i.key)).toEqual(['info', 'note', 'tip', 'warning', 'success', 'error']);
```

and add two rows to the `it.each([...])` list, after `['warning', '> [!warning]'],`:

```ts
    ['success', '> [!success]'],
    ['error', '> [!error]'],
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/toolbar-actions.test.ts src/renderer/__tests__/insert-menu.test.ts src/renderer/__tests__/slash.test.ts`
Expected: FAIL. The two new modules cannot be resolved, and `slash.test.ts` fails with `no slash item success` and the panel list mismatch.

- [ ] **Step 3: Implement**

`desktop/src/renderer/lib/editor/slash.ts`: insert after the `warning` item:

```ts
  { key: 'success', title: 'Success panel', run: (e, r) => e.chain().focus().deleteRange(r).setCallout({ kind: 'success' }).run() },
  { key: 'error', title: 'Error panel', run: (e, r) => e.chain().focus().deleteRange(r).setCallout({ kind: 'error' }).run() },
```

Create `desktop/src/renderer/lib/editor/toolbar-actions.ts`:

```ts
import type { Editor } from '@tiptap/core';
import { isMac } from '../platform';

/** A TipTap keymap entry: Mod (+Shift)(+Alt) + key. Mod = ⌘ / Ctrl. */
export interface ShortcutSpec {
  key: string;
  shift?: boolean;
  alt?: boolean;
}

/** Same style as A4's shortcutLabel: '⌘ ⇧ S', 'Ctrl Alt 2'. */
export function shortcutText(s: ShortcutSpec, mac = isMac): string {
  const parts = [mac ? '⌘' : 'Ctrl'];
  if (s.shift) parts.push('⇧');
  if (s.alt) parts.push(mac ? '⌥' : 'Alt');
  parts.push(s.key.toUpperCase());
  return parts.join(' ');
}

export function withShortcut(label: string, s?: ShortcutSpec, mac = isMac): string {
  return s ? `${label} (${shortcutText(s, mac)})` : label;
}

export interface ToolbarAction {
  /** aria-label (lowercase, stable for tests). */
  id: string;
  /** Tooltip text. */
  label: string;
  icon: string;
  /** The keymap StarterKit / TaskList already binds — never a new binding. */
  shortcut?: ShortcutSpec;
  run: (editor: Editor) => void;
  isActive: (editor: Editor) => boolean;
}

export const MARK_ACTIONS: ToolbarAction[] = [
  { id: 'bold', label: 'Bold', icon: 'bold', shortcut: { key: 'b' }, run: (e) => e.chain().focus().toggleBold().run(), isActive: (e) => e.isActive('bold') },
  { id: 'italic', label: 'Italic', icon: 'italic', shortcut: { key: 'i' }, run: (e) => e.chain().focus().toggleItalic().run(), isActive: (e) => e.isActive('italic') },
  { id: 'strikethrough', label: 'Strikethrough', icon: 'strikethrough', shortcut: { key: 's', shift: true }, run: (e) => e.chain().focus().toggleStrike().run(), isActive: (e) => e.isActive('strike') },
  { id: 'code', label: 'Inline code', icon: 'code', shortcut: { key: 'e' }, run: (e) => e.chain().focus().toggleCode().run(), isActive: (e) => e.isActive('code') },
];

export const LIST_ACTIONS: ToolbarAction[] = [
  { id: 'bullet list', label: 'Bullet list', icon: 'list', shortcut: { key: '8', shift: true }, run: (e) => e.chain().focus().toggleBulletList().run(), isActive: (e) => e.isActive('bulletList') },
  { id: 'numbered list', label: 'Numbered list', icon: 'list-ordered', shortcut: { key: '7', shift: true }, run: (e) => e.chain().focus().toggleOrderedList().run(), isActive: (e) => e.isActive('orderedList') },
  { id: 'task list', label: 'Task list', icon: 'list-checks', shortcut: { key: '9', shift: true }, run: (e) => e.chain().focus().toggleTaskList().run(), isActive: (e) => e.isActive('taskList') },
];

export interface TextStyle {
  id: 'paragraph' | 'h1' | 'h2' | 'h3';
  label: string;
  shortcut: ShortcutSpec;
  run: (editor: Editor) => void;
  isActive: (editor: Editor) => boolean;
}

export const TEXT_STYLES: TextStyle[] = [
  { id: 'paragraph', label: 'Normal text', shortcut: { key: '0', alt: true }, run: (e) => e.chain().focus().setParagraph().run(), isActive: (e) => e.isActive('paragraph') },
  { id: 'h1', label: 'Heading 1', shortcut: { key: '1', alt: true }, run: (e) => e.chain().focus().setHeading({ level: 1 }).run(), isActive: (e) => e.isActive('heading', { level: 1 }) },
  { id: 'h2', label: 'Heading 2', shortcut: { key: '2', alt: true }, run: (e) => e.chain().focus().setHeading({ level: 2 }).run(), isActive: (e) => e.isActive('heading', { level: 2 }) },
  { id: 'h3', label: 'Heading 3', shortcut: { key: '3', alt: true }, run: (e) => e.chain().focus().setHeading({ level: 3 }).run(), isActive: (e) => e.isActive('heading', { level: 3 }) },
];

export function currentTextStyle(editor: Editor): string {
  const hit = TEXT_STYLES.find((s) => s.isActive(editor));
  if (hit) return hit.label;
  for (const level of [4, 5, 6] as const) {
    if (editor.isActive('heading', { level })) return `Heading ${level}`;
  }
  return 'Normal text';
}

const SAFE_SCHEME = /^(?:https?:|mailto:)/i;
const ANY_SCHEME = /^[a-z][a-z0-9+.-]*:/i;
const HOST_PORT = /^[\w.-]+:\d+(?:[/?#]|$)/;

/** http(s) and mailto only; a bare host gets https://. Never javascript:, file:, data:. */
export function normalizeLinkHref(
  raw: string,
): { ok: true; href: string } | { ok: false; error: string } {
  const v = raw.trim();
  if (v === '') return { ok: false, error: 'Enter a link' };
  if (/\s/.test(v)) return { ok: false, error: 'Links cannot contain spaces' };
  if (SAFE_SCHEME.test(v)) return { ok: true, href: v };
  if (ANY_SCHEME.test(v) && !HOST_PORT.test(v)) {
    return { ok: false, error: 'Use an http, https or mailto link' };
  }
  return { ok: true, href: `https://${v}` };
}

/** href null removes the link around the cursor/selection. With nothing
 * selected and no link under the cursor, the address itself is inserted. */
export function applyLink(editor: Editor, href: string | null): void {
  if (href === null) {
    editor.chain().focus().extendMarkRange('link').unsetLink().run();
    return;
  }
  if (editor.state.selection.empty && !editor.isActive('link')) {
    editor
      .chain()
      .focus()
      .insertContent({ type: 'text', text: href, marks: [{ type: 'link', attrs: { href } }] })
      .run();
    return;
  }
  editor.chain().focus().extendMarkRange('link').setLink({ href }).run();
}
```

Create `desktop/src/renderer/lib/editor/insert-menu.ts`:

```ts
import type { Editor } from '@tiptap/core';
import { SLASH_ITEMS, type SlashItem } from './slash';

/** One row of the toolbar's "+ Insert" menu. A 'slash' row runs A1's slash
 * command with the same key, so this menu and "/" can never drift. */
export interface InsertEntry {
  key: string;
  label: string;
  icon: string;
  kind: 'slash' | 'image' | 'assist';
}

type Row = Omit<InsertEntry, 'kind'>;

const BLOCKS: Row[] = [
  { key: 'info', label: 'Info panel', icon: 'info' },
  { key: 'note', label: 'Note panel', icon: 'sticky-note' },
  { key: 'success', label: 'Success panel', icon: 'circle-check' },
  { key: 'warning', label: 'Warning panel', icon: 'triangle-alert' },
  { key: 'error', label: 'Error panel', icon: 'circle-x' },
  { key: 'tip', label: 'Tip panel', icon: 'lightbulb' },
  { key: 'expand', label: 'Expand', icon: 'list-collapse' },
  { key: 'status', label: 'Status', icon: 'tag' },
  { key: 'toc', label: 'Table of contents', icon: 'list-tree' },
  { key: 'diagram', label: 'Mermaid diagram', icon: 'workflow' },
];

const AFTER_IMAGE: Row[] = [
  { key: 'photo', label: 'Photo (webcam)', icon: 'camera' },
  { key: 'table', label: 'Table', icon: 'table' },
  { key: 'divider', label: 'Divider', icon: 'minus' },
  { key: 'code', label: 'Code block', icon: 'square-code' },
  { key: 'quote', label: 'Quote', icon: 'quote' },
  // C1 appends this slash item; until then the row is feature-checked out.
  { key: 'template', label: 'Template', icon: 'layout-template' },
];

export interface InsertOptions {
  slashItems?: readonly SlashItem[];
  /** The editor can take a picked image file (not read-only). */
  canPickImage: boolean;
  /** A5 inline AI handler present. */
  canAssist: boolean;
}

export function insertEntries({
  slashItems = SLASH_ITEMS,
  canPickImage,
  canAssist,
}: InsertOptions): InsertEntry[] {
  const have = new Set(slashItems.map((i) => i.key));
  const slash = (rows: Row[]): InsertEntry[] =>
    rows.filter((r) => have.has(r.key)).map((r): InsertEntry => ({ ...r, kind: 'slash' }));
  const out: InsertEntry[] = [...slash(BLOCKS)];
  if (canPickImage) out.push({ key: 'image', label: 'Image', icon: 'image', kind: 'image' });
  out.push(...slash(AFTER_IMAGE));
  if (canAssist) out.push({ key: 'assist', label: 'Ask AI', icon: 'sparkles', kind: 'assist' });
  return out;
}

/** Run A1's slash command `key` at the cursor (an empty range, so nothing
 * is deleted first). False for an unknown key or a read-only editor. */
export function runInsert(
  editor: Editor,
  key: string,
  slashItems: readonly SlashItem[] = SLASH_ITEMS,
): boolean {
  const item = slashItems.find((i) => i.key === key);
  if (!item || !editor.isEditable) return false;
  const { from } = editor.state.selection;
  item.run(editor, { from, to: from });
  return true;
}
```

- [ ] **Step 4: Run the tests**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/toolbar-actions.test.ts src/renderer/__tests__/insert-menu.test.ts src/renderer/__tests__/slash.test.ts && npm run typecheck`
Expected: PASS. If a shortcut row fails, the binding in `toolbar-actions.ts` is wrong for this TipTap version. Fix the spec to the real keymap (read `node_modules/@tiptap/extension-*/dist/index.js` `addKeyboardShortcuts`). Never add a new keymap to make the test pass.

- [ ] **Step 5: Commit**

```bash
cd "$A7" && git add desktop/src/renderer/lib/editor/toolbar-actions.ts desktop/src/renderer/lib/editor/insert-menu.ts desktop/src/renderer/lib/editor/slash.ts desktop/src/renderer/__tests__/toolbar-actions.test.ts desktop/src/renderer/__tests__/insert-menu.test.ts desktop/src/renderer/__tests__/slash.test.ts
git commit -m "feat(editor): toolbar actions with verified shortcuts, safe links and an insert model over A1's slash items (A7)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The Confluence toolbar

**Files:**
- Create: `desktop/src/renderer/components/editor-toolbar/ToolbarMenu.tsx`, `desktop/src/renderer/components/editor-toolbar/LinkEditor.tsx`
- Modify (rewrite): `desktop/src/renderer/components/EditorToolbar.tsx`
- Test (rewrite): `desktop/src/renderer/__tests__/EditorToolbar.test.tsx`

**Interfaces:**
- Consumes: Task 1 `useSettings` `pageWidth` and `set('pageWidth', …)`; Task 4 `MARK_ACTIONS`, `LIST_ACTIONS`, `TEXT_STYLES`, `currentTextStyle`, `shortcutText`, `withShortcut`, `normalizeLinkHref`, `applyLink`, `insertEntries` and `runInsert`; `Lucide`; `toast`.
- Produces:
  - `EditorToolbar(props: { editor: Editor | null; onImageFile?: (file: File) => void; onAssist?: () => void })`, rendered as `role="toolbar"` `aria-label="formatting"`. Buttons: `bold`, `italic`, `strikethrough`, `code`, `bullet list`, `numbered list`, `task list`, `link`, `table`, `text style` (menu), `insert` (menu) and `full width` (`aria-pressed`). Hidden `<input type="file" data-testid="image-picker">`.
  - `ToolbarMenu(props: { label: string; title?: string; trigger: React.ReactNode; items: ToolbarMenuItem[]; radio?: boolean })` with `ToolbarMenuItem { key: string; label: string; icon?: string; hint?: string; checked?: boolean; onSelect: () => void }`.
  - `LinkEditor(props: { editor: Editor })`: an inline form `role="dialog"` `aria-label="edit link"` with an input labelled `link address` and buttons `Apply` and `Remove link`.
  - `onPhoto` is removed (Photo runs the `photo` slash item).

- [ ] **Step 1: Write the failing tests**

Replace the whole of `desktop/src/renderer/__tests__/EditorToolbar.test.tsx` with:

```tsx
import { createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Editor } from '@tiptap/core';
import { EditorToolbar } from '../components/EditorToolbar';
import { SLASH_ITEMS } from '../lib/editor/slash';
import { useSettings } from '../stores/settings';
import { makeEditor, markdownOf } from './helpers/editor';

let editor: Editor;

afterEach(() => {
  editor?.destroy();
  useSettings.setState({ pageWidth: 'fixed' });
});

function setup(content = 'word', props: Partial<React.ComponentProps<typeof EditorToolbar>> = {}) {
  editor = makeEditor(content);
  render(<EditorToolbar editor={editor} {...props} />);
  return editor;
}

const openInsert = () => fireEvent.click(screen.getByRole('button', { name: 'insert' }));

describe('EditorToolbar (A7)', () => {
  it('toggles marks on the selection and shows the shortcut in the tooltip', () => {
    setup();
    editor.commands.selectAll();
    fireEvent.click(screen.getByRole('button', { name: 'bold' }));
    fireEvent.click(screen.getByRole('button', { name: 'strikethrough' }));
    expect(editor.isActive('bold')).toBe(true);
    expect(editor.isActive('strike')).toBe(true);
    const bold = screen.getByRole('button', { name: 'bold' });
    expect(bold).toHaveAttribute('title', 'Bold (⌘ B)');
    expect(bold).toHaveAttribute('aria-pressed', 'true');
  });

  it('numbered list', () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'numbered list' }));
    expect(markdownOf(editor)).toBe('1. word');
  });

  it('text style menu sets headings and back to normal text', () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'text style' }));
    fireEvent.click(screen.getByRole('menuitemradio', { name: /^Heading 2/ }));
    expect(editor.isActive('heading', { level: 2 })).toBe(true);
    expect(screen.getByRole('button', { name: 'text style' })).toHaveTextContent('Heading 2');
    fireEvent.click(screen.getByRole('button', { name: 'text style' }));
    expect(screen.getByRole('menuitemradio', { name: /^Heading 2/ })).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(screen.getByRole('menuitemradio', { name: /^Normal text/ }));
    expect(markdownOf(editor)).toBe('word');
  });

  it('insert lists every block in order; Template only with C1, Ask AI only with a handler', () => {
    setup('word', { onImageFile: () => {} });
    openInsert();
    const names = screen.getAllByRole('menuitem').map((m) => m.textContent);
    const base = [
      'Info panel', 'Note panel', 'Success panel', 'Warning panel', 'Error panel', 'Tip panel',
      'Expand', 'Status', 'Table of contents', 'Mermaid diagram', 'Image', 'Photo (webcam)',
      'Table', 'Divider', 'Code block', 'Quote',
    ];
    const hasTemplate = SLASH_ITEMS.some((i) => i.key === 'template');
    expect(names).toEqual(hasTemplate ? [...base, 'Template'] : base);
  });

  it('Ask AI calls the assist handler', () => {
    const onAssist = vi.fn();
    setup('word', { onAssist });
    openInsert();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Ask AI' }));
    expect(onAssist).toHaveBeenCalledOnce();
  });

  it('inserting an error panel runs the A1 callout command', () => {
    setup('');
    openInsert();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Error panel' }));
    expect(markdownOf(editor)).toBe('> [!error]');
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('Image opens the file picker and hands the picked file over', () => {
    const onImageFile = vi.fn();
    setup('word', { onImageFile });
    const picker = screen.getByTestId('image-picker') as HTMLInputElement;
    const click = vi.spyOn(picker, 'click').mockImplementation(() => {});
    openInsert();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Image' }));
    expect(click).toHaveBeenCalledOnce();
    const file = new File(['x'], 'a.png', { type: 'image/png' });
    fireEvent.change(picker, { target: { files: [file] } });
    expect(onImageFile).toHaveBeenCalledWith(file);
  });

  it('no Image row without an image handler', () => {
    setup();
    openInsert();
    expect(screen.queryByRole('menuitem', { name: 'Image' })).toBeNull();
  });

  it('Esc closes a menu and is consumed so the note viewer stays open', () => {
    setup();
    openInsert();
    const item = screen.getAllByRole('menuitem')[0]!;
    const esc = createEvent.keyDown(item, { key: 'Escape' });
    fireEvent(item, esc);
    expect(esc.defaultPrevented).toBe(true);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('arrow keys move through the menu and wrap', () => {
    setup();
    openInsert();
    const items = screen.getAllByRole('menuitem');
    expect(items[0]).toHaveFocus();
    fireEvent.keyDown(items[0]!, { key: 'ArrowDown' });
    expect(items[1]).toHaveFocus();
    fireEvent.keyDown(items[1]!, { key: 'ArrowUp' });
    fireEvent.keyDown(items[0]!, { key: 'ArrowUp' });
    expect(items.at(-1)).toHaveFocus();
  });

  it('link: applies a normalised address to the selection', () => {
    setup();
    editor.commands.selectAll();
    fireEvent.click(screen.getByRole('button', { name: 'link' }));
    fireEvent.change(screen.getByLabelText('link address'), { target: { value: 'example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(editor.getAttributes('link').href).toBe('https://example.com');
    expect(screen.queryByRole('dialog', { name: 'edit link' })).toBeNull();
  });

  it('link: refuses script addresses', () => {
    setup();
    editor.commands.selectAll();
    fireEvent.click(screen.getByRole('button', { name: 'link' }));
    fireEvent.change(screen.getByLabelText('link address'), { target: { value: 'javascript:alert(1)' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Use an http, https or mailto link');
    expect(editor.isActive('link')).toBe(false);
  });

  it('link: prefills the current address and removes the link', () => {
    setup('[word](https://a.example)');
    editor.commands.selectAll();
    fireEvent.click(screen.getByRole('button', { name: 'link' }));
    expect(screen.getByLabelText('link address')).toHaveValue('https://a.example');
    fireEvent.click(screen.getByRole('button', { name: 'Remove link' }));
    expect(markdownOf(editor)).toBe('word');
  });

  it('link: Esc closes the form and is consumed', () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'link' }));
    const input = screen.getByLabelText('link address');
    const esc = createEvent.keyDown(input, { key: 'Escape' });
    fireEvent(input, esc);
    expect(esc.defaultPrevented).toBe(true);
    expect(screen.queryByRole('dialog', { name: 'edit link' })).toBeNull();
  });

  it('table inserts the A1 table', () => {
    setup('');
    fireEvent.click(screen.getByRole('button', { name: 'table' }));
    expect(editor.isActive('table')).toBe(true);
  });

  it('page width toggle flips the global setting', async () => {
    setup();
    const btn = screen.getByRole('button', { name: 'full width' });
    expect(btn).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(btn);
    await waitFor(() => expect(useSettings.getState().pageWidth).toBe('full'));
    expect(screen.getByRole('button', { name: 'full width' })).toHaveAttribute('aria-pressed', 'true');
  });
});
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/EditorToolbar.test.tsx`
Expected: FAIL. There is no `strikethrough`, `text style`, `insert`, `link` or `full width` button.

- [ ] **Step 3: Implement**

Create `desktop/src/renderer/components/editor-toolbar/ToolbarMenu.tsx`:

```tsx
import { useEffect, useRef, useState } from 'react';
import { Lucide } from '../Lucide';

export interface ToolbarMenuItem {
  key: string;
  label: string;
  icon?: string;
  /** Right-aligned hint (a shortcut). */
  hint?: string;
  /** For radio menus: the current choice. */
  checked?: boolean;
  onSelect: () => void;
}

interface Props {
  /** aria-label of the trigger and the menu. */
  label: string;
  title?: string;
  trigger: React.ReactNode;
  items: ToolbarMenuItem[];
  radio?: boolean;
}

/** Toolbar dropdown. Esc closes it and is preventDefault-ed, so NoteView's
 * Esc-to-close and A4's Esc-to-leave-focus both skip it. */
export function ToolbarMenu({ label, title, trigger, items, radio = false }: Props) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    if (open) itemRefs.current[active]?.focus();
  }, [open, active]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open || items.length === 0) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => (i + 1) % items.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => (i - 1 + items.length) % items.length);
    }
  };

  return (
    <div ref={rootRef} className="relative" onKeyDown={onKeyDown}>
      <button
        type="button"
        aria-label={label}
        title={title ?? label}
        aria-haspopup="menu"
        aria-expanded={open}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => {
          setActive(0);
          setOpen((o) => !o);
        }}
        className={`flex h-7 items-center gap-1 rounded-sm px-2 text-ink-1 hover:bg-fog hover:text-ink-0 ${
          open ? 'bg-fog text-ink-0' : ''
        }`}
      >
        {trigger}
      </button>
      {open && (
        <div
          role="menu"
          aria-label={label}
          className="absolute left-0 top-full z-30 mt-1 max-h-[60vh] min-w-[224px] overflow-y-auto rounded-md border border-hairline-2 bg-vellum p-1 shadow-float"
        >
          {items.map((it, i) => (
            <button
              key={it.key}
              ref={(el) => {
                itemRefs.current[i] = el;
              }}
              type="button"
              role={radio ? 'menuitemradio' : 'menuitem'}
              aria-checked={radio ? it.checked === true : undefined}
              tabIndex={i === active ? 0 : -1}
              onMouseEnter={() => setActive(i)}
              onClick={() => {
                setOpen(false);
                it.onSelect();
              }}
              className={`flex w-full items-center gap-2 rounded-sm px-2 py-[6px] text-left text-12 text-ink-1 outline-none hover:bg-fog hover:text-ink-0 focus-visible:bg-fog focus-visible:text-ink-0 ${
                it.checked ? 'text-ink-0' : ''
              }`}
            >
              {it.icon && <Lucide name={it.icon} size={14} />}
              <span className="flex-1">{it.label}</span>
              {it.hint && <span className="font-mono text-10 text-ink-3">{it.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

Create `desktop/src/renderer/components/editor-toolbar/LinkEditor.tsx`:

```tsx
import { useState } from 'react';
import type { Editor } from '@tiptap/core';
import { applyLink, normalizeLinkHref } from '../../lib/editor/toolbar-actions';
import { Lucide } from '../Lucide';

/** Link button + inline address form (Electron has no window.prompt).
 * No shortcut: ⌘K is the Today search. */
export function LinkEditor({ editor }: { editor: Editor }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const active = editor.isActive('link');

  const show = () => {
    setValue((editor.getAttributes('link').href as string | undefined) ?? '');
    setError(null);
    setOpen(true);
  };
  const close = () => {
    setOpen(false);
    editor.commands.focus();
  };
  const apply = () => {
    const r = normalizeLinkHref(value);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    applyLink(editor, r.href);
    setOpen(false);
  };

  return (
    <div className="relative">
      <button
        type="button"
        aria-label="link"
        title="Link"
        aria-pressed={active}
        aria-expanded={open}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => (open ? setOpen(false) : show())}
        className={`flex h-7 w-7 items-center justify-center rounded-sm hover:bg-fog hover:text-ink-0 ${
          active ? 'bg-fog text-ink-0' : 'text-ink-2'
        }`}
      >
        <Lucide name="link" size={14} />
      </button>
      {open && (
        <form
          role="dialog"
          aria-label="edit link"
          onSubmit={(e) => {
            e.preventDefault();
            apply();
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              e.stopPropagation();
              close();
            }
          }}
          className="absolute left-0 top-full z-30 mt-1 w-[300px] rounded-md border border-hairline-2 bg-vellum p-2 shadow-float"
        >
          <input
            autoFocus
            aria-label="link address"
            value={value}
            placeholder="https://…"
            onChange={(e) => {
              setValue(e.target.value);
              setError(null);
            }}
            className="w-full rounded-sm border border-hairline-2 bg-paper px-2 py-[5px] text-12 text-ink-0 outline-none focus:border-hairline-3"
          />
          {error && (
            <div role="alert" className="mt-1 text-11 text-oxblood">
              {error}
            </div>
          )}
          <div className="mt-2 flex justify-end gap-1">
            {active && (
              <button
                type="button"
                onClick={() => {
                  applyLink(editor, null);
                  setOpen(false);
                }}
                className="rounded-sm px-2 py-[3px] text-11 text-ink-2 hover:bg-fog hover:text-ink-0"
              >
                Remove link
              </button>
            )}
            <button
              type="submit"
              className="rounded-sm bg-fog px-2 py-[3px] text-11 text-ink-0 hover:bg-hairline-2"
            >
              Apply
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
```

Replace the whole of `desktop/src/renderer/components/EditorToolbar.tsx` with:

```tsx
import { useEffect, useRef, useState } from 'react';
import type { Editor } from '@tiptap/core';
import { insertEntries, runInsert } from '../lib/editor/insert-menu';
import {
  LIST_ACTIONS,
  MARK_ACTIONS,
  TEXT_STYLES,
  currentTextStyle,
  shortcutText,
  withShortcut,
  type ToolbarAction,
} from '../lib/editor/toolbar-actions';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { LinkEditor } from './editor-toolbar/LinkEditor';
import { ToolbarMenu, type ToolbarMenuItem } from './editor-toolbar/ToolbarMenu';
import { Lucide } from './Lucide';

export interface EditorToolbarProps {
  editor: Editor | null;
  /** Inserts a picked image file. Absent → no Image row (read-only). */
  onImageFile?: (file: File) => void;
  /** A5 inline AI. Absent → no Ask AI row. */
  onAssist?: () => void;
}

const Divider = () => <span aria-hidden className="mx-1 h-4 w-px flex-shrink-0 bg-hairline-2" />;

function ActionButton({ editor, action }: { editor: Editor; action: ToolbarAction }) {
  const on = action.isActive(editor);
  return (
    <button
      type="button"
      aria-label={action.id}
      title={withShortcut(action.label, action.shortcut)}
      aria-pressed={on}
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => action.run(editor)}
      className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-sm hover:bg-fog hover:text-ink-0 ${
        on ? 'bg-fog text-ink-0' : 'text-ink-2'
      }`}
    >
      <Lucide name={action.icon} size={14} />
    </button>
  );
}

function PageWidthToggle() {
  const width = useSettings((s) => s.pageWidth);
  const set = useSettings((s) => s.set);
  const full = width === 'full';
  return (
    <button
      type="button"
      aria-label="full width"
      aria-pressed={full}
      title={full ? 'Fixed width' : 'Full width'}
      onMouseDown={(e) => e.preventDefault()}
      onClick={() =>
        void set('pageWidth', full ? 'fixed' : 'full').then((r) => {
          if (!r.ok) toast.error(r.error);
        })
      }
      className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-sm hover:bg-fog hover:text-ink-0 ${
        full ? 'bg-fog text-ink-0' : 'text-ink-2'
      }`}
    >
      <Lucide name="move-horizontal" size={14} />
    </button>
  );
}

/** A7: the page's one fixed formatting toolbar (Confluence layout). */
export function EditorToolbar({ editor, onImageFile, onAssist }: EditorToolbarProps) {
  // Re-render on selection/content changes so active states stay accurate.
  const [, force] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!editor) return;
    const update = () => force((n) => n + 1);
    editor.on('selectionUpdate', update);
    editor.on('transaction', update);
    return () => {
      editor.off('selectionUpdate', update);
      editor.off('transaction', update);
    };
  }, [editor]);

  if (!editor) return null;

  const styleItems: ToolbarMenuItem[] = TEXT_STYLES.map((s) => ({
    key: s.id,
    label: s.label,
    hint: shortcutText(s.shortcut),
    checked: s.isActive(editor),
    onSelect: () => s.run(editor),
  }));

  const insertItems: ToolbarMenuItem[] = insertEntries({
    canPickImage: onImageFile !== undefined,
    canAssist: onAssist !== undefined,
  }).map((en) => ({
    key: en.key,
    label: en.label,
    icon: en.icon,
    onSelect: () => {
      if (en.kind === 'image') fileRef.current?.click();
      else if (en.kind === 'assist') onAssist?.();
      else runInsert(editor, en.key);
    },
  }));

  return (
    <div
      role="toolbar"
      aria-label="formatting"
      className="flex h-10 flex-shrink-0 items-center gap-[2px] overflow-x-auto border-b border-hairline bg-paper px-3"
    >
      <ToolbarMenu
        label="text style"
        title="Text style"
        radio
        items={styleItems}
        trigger={
          <>
            <span className="w-[88px] truncate text-left text-12">{currentTextStyle(editor)}</span>
            <Lucide name="chevron-down" size={12} />
          </>
        }
      />
      <Divider />
      {MARK_ACTIONS.map((a) => (
        <ActionButton key={a.id} editor={editor} action={a} />
      ))}
      <Divider />
      {LIST_ACTIONS.map((a) => (
        <ActionButton key={a.id} editor={editor} action={a} />
      ))}
      <Divider />
      <LinkEditor editor={editor} />
      <button
        type="button"
        aria-label="table"
        title="Table"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => runInsert(editor, 'table')}
        className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-sm text-ink-2 hover:bg-fog hover:text-ink-0"
      >
        <Lucide name="table" size={14} />
      </button>
      <Divider />
      <ToolbarMenu
        label="insert"
        title="Insert"
        items={insertItems}
        trigger={
          <>
            <Lucide name="plus" size={14} />
            <span className="text-12 text-ink-0">Insert</span>
            <Lucide name="chevron-down" size={12} />
          </>
        }
      />
      <div className="ml-auto flex items-center">
        <PageWidthToggle />
      </div>
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        hidden
        data-testid="image-picker"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = '';
          if (file && onImageFile) onImageFile(file);
        }}
      />
    </div>
  );
}
```

At this point `RichMarkdownEditor` still passes `onPhoto`, so the typecheck fails until Task 6. Do not run the typecheck as a gate in this task.

- [ ] **Step 4: Run the tests**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/EditorToolbar.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$A7" && git add desktop/src/renderer/components/EditorToolbar.tsx desktop/src/renderer/components/editor-toolbar/ToolbarMenu.tsx desktop/src/renderer/components/editor-toolbar/LinkEditor.tsx desktop/src/renderer/__tests__/EditorToolbar.test.tsx
git commit -m "feat(editor): confluence-style toolbar with text styles, link form, insert menu and page width (A7)

RichMarkdownEditor still passes onPhoto; Task 6 rewires it.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Page canvas in `RichMarkdownEditor`

**Files:**
- Modify: `desktop/src/renderer/components/RichMarkdownEditor.tsx` (the A1 + A4 merged version), `desktop/src/renderer/styles.css`
- Test: `desktop/src/renderer/__tests__/RichMarkdownEditor-page.test.tsx`

**Interfaces:**
- Consumes: Task 1 `pageWidth`; Task 5 `EditorToolbar({ editor, onImageFile, onAssist? })`; `insertImageFile(editor, jotId, file)` (`lib/editor/insert-image.ts`); A1's `TableToolbar`, `StatusPopover` and `DiagramModal`, which stay where A1 put them.
- Produces:
  - `RichMarkdownEditorProps.pageHeader?: React.ReactNode`, rendered first inside the canvas, above the document. It is kept in source mode.
  - Canvas element `data-testid="page-canvas"` `className="gb-page"` `data-width={focus ? 'fixed' : pageWidth}`.
  - The toolbar is hidden when `readOnly` (as well as in focus mode and source mode).
  - CSS classes `.gb-page`, `.gb-page-header`, `.gb-page-title`, `.gb-page-body`. A4's `[data-focus='on'] .ProseMirror` rule is removed.

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/RichMarkdownEditor-page.test.tsx`:

```tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { Editor } from '@tiptap/core';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';
import { getMarkdown } from '../lib/editor/markdown';
import { useSettings } from '../stores/settings';

afterEach(() => useSettings.setState({ pageWidth: 'fixed' }));

describe('RichMarkdownEditor page canvas (A7)', () => {
  it('renders the page header above the document inside the canvas', () => {
    render(
      <RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" pageHeader={<div data-testid="hdr">hdr</div>} />,
    );
    const canvas = screen.getByTestId('page-canvas');
    const hdr = screen.getByTestId('hdr');
    const pm = canvas.querySelector('.ProseMirror');
    expect(canvas).toContainElement(hdr);
    expect(pm).not.toBeNull();
    expect(hdr.compareDocumentPosition(pm!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('follows the page width setting; focus mode always uses the fixed measure', () => {
    useSettings.setState({ pageWidth: 'full' });
    const { rerender } = render(<RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" />);
    expect(screen.getByTestId('page-canvas')).toHaveAttribute('data-width', 'full');
    rerender(<RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" focus />);
    expect(screen.getByTestId('page-canvas')).toHaveAttribute('data-width', 'fixed');
  });

  it('keeps the header in source mode', () => {
    render(
      <RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" pageHeader={<div data-testid="hdr">hdr</div>} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'src' }));
    expect(screen.getByTestId('hdr')).toBeInTheDocument();
    expect(screen.queryByRole('toolbar', { name: 'formatting' })).toBeNull();
  });

  it('hides the toolbar when read-only', () => {
    render(<RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" readOnly />);
    expect(screen.queryByRole('toolbar', { name: 'formatting' })).toBeNull();
  });

  it('inserts a picked image file into the page', async () => {
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="body"
        onSave={() => {}}
        jotId="j1"
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    const file = new File([new Uint8Array([1, 2, 3])], 'shot.png', { type: 'image/png' });
    fireEvent.change(screen.getByTestId('image-picker'), { target: { files: [file] } });
    await waitFor(() =>
      expect(getMarkdown(editor!)).toContain('90-meta/assets/jots/2026/06/stub-x.jpg'),
    );
  });
});
```

(The asset path is the `assets.write` stub in `test/setup.ts`.)

- [ ] **Step 2: Run it to see it fail**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/RichMarkdownEditor-page.test.tsx`
Expected: FAIL. There is no `page-canvas` element and no `image-picker` wiring.

- [ ] **Step 3: Implement**

`desktop/src/renderer/components/RichMarkdownEditor.tsx`. Read the merged file first: it has A1's `TableToolbar`/`StatusPopover`/`DiagramModal` and A4's `focus`/`ReadAloudControls`.

(a) Add the import:

```ts
import { useSettings } from '../stores/settings';
```

(b) In `interface RichMarkdownEditorProps`, after the `focus?: boolean;` member:

```ts
  /** A7: page header (breadcrumb, title, byline) shown above the document
   * inside the page canvas. GuardedNoteEditor supplies it in page mode. */
  pageHeader?: React.ReactNode;
```

(c) Add `pageHeader,` to the destructured props (after `focus = false,`). Then, right after `const [camOpen, setCamOpen] = useState(false);`:

```ts
  const pageWidth = useSettings((s) => s.pageWidth);
```

(d) Right before `function switchMode(next: Mode) {`:

```ts
  function insertPickedImage(file: File) {
    if (!editorRef.current) return;
    void insertImageFile(editorRef.current, jotIdRef.current, file).catch((e: Error) =>
      toast.error(`image insert failed: ${e.message}`),
    );
  }
```

(e) In the returned JSX, replace everything from the toolbar line through the end of the scroll area. The merged file has this shape:

```tsx
      {mode === 'rich' && editor && !focus && (
        <EditorToolbar editor={editor} onPhoto={() => setCamOpen(true)} />
      )}
      <div className="flex-1 overflow-auto">
        {mode === 'rich' && editor && !readOnly && <TableToolbar editor={editor} />}
        {mode === 'rich' ? (
          <EditorContent … />
        ) : (
          <JotEditor … />
        )}
      </div>
```

Replace it with:

```tsx
      {mode === 'rich' && editor && !focus && !readOnly && (
        <EditorToolbar editor={editor} onImageFile={insertPickedImage} />
      )}
      <div className="flex-1 overflow-auto">
        {mode === 'rich' && editor && !readOnly && <TableToolbar editor={editor} />}
        <div
          className="gb-page"
          data-testid="page-canvas"
          data-width={focus ? 'fixed' : pageWidth}
        >
          {pageHeader}
          {mode === 'rich' ? (
            <EditorContent
              editor={editor}
              className="gb-prose gb-page-body text-ink-0 [&_.ProseMirror]:min-h-[40vh] [&_.ProseMirror]:outline-none"
            />
          ) : (
            <JotEditor
              body={current.current}
              debounceMs={debounceMs}
              readOnly={readOnly}
              onSave={(next) => {
                current.current = next;
                lastSaved.current = next;
                onSave(next);
              }}
            />
          )}
        </div>
      </div>
```

Keep the `JotEditor` props exactly as they are in the merged file. The block above repeats main's version. If A1 changed them, keep A1's. Leave the footer (copy formatted, `ReadAloudControls`, rich/src), the `StatusPopover`/`DiagramModal` and `WebcamCaptureModal` unchanged. The webcam still opens through the existing `gb:slash:photo` listener and `openCameraSignal`.

`desktop/src/renderer/styles.css`: replace A4's block

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

with

```css
/* A7 page canvas: a centred document column. Width is the global
   `pageWidth` setting; focus mode (A4) always uses the fixed measure. */
.gb-page {
  --gb-page-measure: 44rem; /* ≈80 characters of 16px body text */
  box-sizing: border-box;
  width: 100%;
  margin: 0 auto;
  padding: 40px 48px 30vh;
}
.gb-page[data-width='fixed'] { max-width: calc(var(--gb-page-measure) + 96px); }
.gb-page[data-width='full'] { max-width: none; }
[data-focus='on'] .gb-page { padding-top: 56px; }
@media (max-width: 720px) {
  .gb-page { padding-left: 20px; padding-right: 20px; }
}
.gb-page-header { margin-bottom: 28px; }
/* The page's one bold element. */
.gb-page-title {
  display: block;
  width: 100%;
  margin: 0;
  padding: 0;
  border: 0;
  outline: none;
  resize: none;
  overflow: hidden;
  background: transparent;
  color: var(--ink-0);
  font-family: var(--font-display);
  font-size: 34px;
  line-height: 1.15;
  font-weight: 640;
  letter-spacing: -0.025em;
  font-variation-settings: 'opsz' 48;
}
.gb-page-title::placeholder { color: var(--ink-3); }
.gb-page-title:focus-visible { box-shadow: 0 2px 0 0 var(--hairline-3); }
.gb-page-body { font-size: 16px; line-height: 1.7; }
.gb-page-body h1 { font-size: 26px; }
.gb-page-body h2 { font-size: 21px; }
.gb-page-body h3 { font-size: 18px; }
.gb-page-body h4 { font-size: 16px; }
```

The `.gb-page-body hN` rules come after the `.gb-prose hN` rules, and with equal specificity the later rule wins.

- [ ] **Step 4: Run the tests and the gates touched so far**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/RichMarkdownEditor-page.test.tsx src/renderer/__tests__/RichMarkdownEditor.test.tsx src/renderer/__tests__/EditorToolbar.test.tsx && npm run typecheck`
Expected: PASS. The existing "focus hides the formatting toolbar and marks the page for centring" test still passes (`bold` is gone in focus mode and `data-focus="on"` is set).

- [ ] **Step 5: Commit**

```bash
cd "$A7" && git add desktop/src/renderer/components/RichMarkdownEditor.tsx desktop/src/renderer/styles.css desktop/src/renderer/__tests__/RichMarkdownEditor-page.test.tsx
git commit -m "feat(editor): centred page canvas with header slot, width setting and image picker (A7)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Page header and title in `GuardedNoteEditor`

**Files:**
- Create: `desktop/src/renderer/components/page/PageTitle.tsx`, `desktop/src/renderer/components/page/PageHeader.tsx`
- Modify: `desktop/src/renderer/components/GuardedNoteEditor.tsx`
- Test: `desktop/src/renderer/__tests__/GuardedNoteEditor-page.test.tsx`

**Interfaces:**
- Consumes: Task 2 `splitPageTitle`, `joinPageTitle`, `retitlePage`, `sanitizePageTitle`, `PageTitleSplit` and `TitleRule`; Task 6 `RichMarkdownEditorProps.pageHeader`; B1's `useGuardedSave` (`save`, `adopt`, `runExclusive`).
- Produces:
  - `interface PageChrome { titleRule: TitleRule; fallbackTitle: string; breadcrumb: string[]; byline?: React.ReactNode }`
  - `GuardedNoteEditorProps.page?: PageChrome`. `editorProps` becomes `Omit<RichMarkdownEditorProps, 'markdown' | 'onSave' | 'pageHeader'>`.
  - `GuardHandle.reload(etag: string | null, body: string): void`: adopts an outside write and remounts the page with that body (the title is re-split).
  - The title textarea has `aria-label="page title"` and placeholder `Untitled`. Breadcrumb is `<nav aria-label="breadcrumb">`. The header is `data-testid="page-header"`.
  - Without `page`, behaviour is exactly as before (the existing `GuardedNoteEditor.test.tsx` is unchanged).

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/GuardedNoteEditor-page.test.tsx`:

```tsx
import { act, createEvent, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Editor } from '@tiptap/core';
import {
  GuardedNoteEditor,
  type GuardHandle,
  type GuardedNoteEditorProps,
  type PageChrome,
} from '../components/GuardedNoteEditor';
import { getMarkdown } from '../lib/editor/markdown';

const E1 = 'aaaaaaaaaaaaaaaa';
const E2 = 'cccccccccccccccc';
const NOTE: PageChrome = { titleRule: 'note', fallbackTitle: '', breadcrumb: ['work', 'payments'] };

function setup(
  initialBody: string,
  page: PageChrome | undefined,
  guardRef?: React.MutableRefObject<GuardHandle | null>,
  extra: Partial<GuardedNoteEditorProps['editorProps']> = {},
) {
  const send = vi.fn().mockResolvedValue({ etag: E2 });
  const fetchLatest = vi.fn().mockResolvedValue({ body: initialBody, etag: E1 });
  let editor: Editor | undefined;
  render(
    <GuardedNoteEditor
      initialBody={initialBody}
      initialEtag={E1}
      send={send}
      fetchLatest={fetchLatest}
      guardRef={guardRef}
      page={page}
      editorProps={{
        jotId: 'n.md',
        debounceMs: 10,
        onEditorReady: (e) => {
          editor = e;
        },
        ...extra,
      }}
    />,
  );
  return { send, getEditor: () => editor };
}

const title = () => screen.getByLabelText('page title') as HTMLTextAreaElement;
const settle = () => new Promise((r) => setTimeout(r, 60));

describe('GuardedNoteEditor page mode (A7)', () => {
  it('shows the leading H1 as the title, the breadcrumb, and only the rest in the editor', async () => {
    const { getEditor } = setup('# Plan\n\nbody text', NOTE);
    expect(title()).toHaveValue('Plan');
    const crumbs = screen.getByRole('navigation', { name: 'breadcrumb' });
    expect(within(crumbs).getByText('work')).toBeInTheDocument();
    expect(within(crumbs).getByText('payments')).toBeInTheDocument();
    await waitFor(() => expect(getEditor()).toBeDefined());
    expect(getMarkdown(getEditor()!).trim()).toBe('body text');
  });

  it('a body edit saves the untouched title line in front of it', async () => {
    const { send, getEditor } = setup('# Plan\n\nbody text', NOTE);
    await waitFor(() => expect(getEditor()).toBeDefined());
    act(() => {
      const ed = getEditor()!;
      ed.commands.insertContentAt(ed.state.doc.content.size, 'my tail');
    });
    await waitFor(() => expect(send).toHaveBeenCalled());
    const body = send.mock.calls.at(-1)![0] as string;
    expect(body.startsWith('# Plan\n\nbody text')).toBe(true);
    expect(body).toContain('my tail');
  });

  it('renaming on blur saves the new H1 with the body unchanged', async () => {
    const { send } = setup('# Plan\n\nbody text', NOTE);
    fireEvent.change(title(), { target: { value: 'Launch plan' } });
    fireEvent.blur(title());
    await waitFor(() => expect(send).toHaveBeenCalledWith('# Launch plan\n\nbody text', E1));
  });

  it('typing in the title saves after the debounce without leaving the field', async () => {
    const { send } = setup('# Plan\n\nbody text', NOTE);
    fireEvent.change(title(), { target: { value: 'Launch' } });
    await waitFor(() => expect(send).toHaveBeenCalledWith('# Launch\n\nbody text', E1));
  });

  it('Enter saves the title and does not add a line break', async () => {
    const { send } = setup('# Plan\n\nbody text', NOTE);
    fireEvent.change(title(), { target: { value: 'Launch plan' } });
    const enter = createEvent.keyDown(title(), { key: 'Enter' });
    fireEvent(title(), enter);
    expect(enter.defaultPrevented).toBe(true);
    await waitFor(() => expect(send).toHaveBeenCalledWith('# Launch plan\n\nbody text', E1));
  });

  it('an unchanged or emptied title saves nothing, and an empty one reverts on blur', async () => {
    const { send } = setup('# Plan\n\nbody text', NOTE);
    fireEvent.blur(title());
    fireEvent.change(title(), { target: { value: '   ' } });
    fireEvent.blur(title());
    expect(title()).toHaveValue('Plan');
    await settle();
    expect(send).not.toHaveBeenCalled();
  });

  it('pasted line breaks become spaces', async () => {
    const { send } = setup('# Plan\n\nbody text', NOTE);
    fireEvent.change(title(), { target: { value: 'Two\nlines' } });
    expect(title()).toHaveValue('Two lines');
    fireEvent.blur(title());
    await waitFor(() => expect(send).toHaveBeenCalledWith('# Two lines\n\nbody text', E1));
  });

  it('Esc with an unsaved title reverts it and is consumed; Esc on a clean title is left alone', () => {
    setup('# Plan\n\nbody text', NOTE);
    fireEvent.change(title(), { target: { value: 'Draft' } });
    const dirty = createEvent.keyDown(title(), { key: 'Escape' });
    fireEvent(title(), dirty);
    expect(dirty.defaultPrevented).toBe(true);
    expect(title()).toHaveValue('Plan');
    const clean = createEvent.keyDown(title(), { key: 'Escape' });
    fireEvent(title(), clean);
    expect(clean.defaultPrevented).toBe(false);
  });

  it('a jot keeps its plain first-line title plain', async () => {
    const { send } = setup('first jot\n\nfull body here', { titleRule: 'jot', fallbackTitle: '', breadcrumb: [] });
    expect(title()).toHaveValue('first jot');
    expect(screen.queryByRole('navigation', { name: 'breadcrumb' })).toBeNull();
    fireEvent.change(title(), { target: { value: 'Sprint retro' } });
    fireEvent.blur(title());
    await waitFor(() => expect(send).toHaveBeenCalledWith('Sprint retro\n\nfull body here', E1));
  });

  it('a note without an H1 shows its fallback title and only writes an H1 when renamed', async () => {
    const { send } = setup('hand-written', { titleRule: 'note', fallbackTitle: 'Spec', breadcrumb: [] });
    expect(title()).toHaveValue('Spec');
    fireEvent.blur(title());
    await settle();
    expect(send).not.toHaveBeenCalled();
    fireEvent.change(title(), { target: { value: 'Spec v2' } });
    fireEvent.blur(title());
    await waitFor(() => expect(send).toHaveBeenCalledWith('# Spec v2\n\nhand-written', E1));
  });

  it('a body with no title and no fallback shows the Untitled placeholder', () => {
    setup('line one\nline two', { titleRule: 'jot', fallbackTitle: '', breadcrumb: [] });
    expect(title()).toHaveValue('');
    expect(title()).toHaveAttribute('placeholder', 'Untitled');
  });

  it('a title rename and body typing in the same debounce window both land', async () => {
    const { send, getEditor } = setup('# Plan\n\nbody text', NOTE);
    await waitFor(() => expect(getEditor()).toBeDefined());
    act(() => {
      const ed = getEditor()!;
      ed.commands.insertContentAt(ed.state.doc.content.size, 'my tail');
    });
    fireEvent.change(title(), { target: { value: 'Launch plan' } });
    fireEvent.blur(title());
    await waitFor(() => {
      const last = send.mock.calls.at(-1)![0] as string;
      expect(last.startsWith('# Launch plan\n\nbody text')).toBe(true);
      expect(last).toContain('my tail');
    });
  });

  it('a history restore re-reads the title from the restored body', async () => {
    const guardRef = { current: null as GuardHandle | null };
    const { getEditor } = setup('# Plan\n\nbody text', NOTE, guardRef);
    await waitFor(() => expect(guardRef.current).not.toBeNull());
    await act(async () => {
      await guardRef.current!.restore(async () => ({ body: '# Old plan\n\nold body', etag: E2 }));
    });
    expect(title()).toHaveValue('Old plan');
    await waitFor(() => expect(getMarkdown(getEditor()!).trim()).toBe('old body'));
  });

  it('reload adopts an outside write and re-splits it', async () => {
    const guardRef = { current: null as GuardHandle | null };
    const { send, getEditor } = setup('# Plan\n\nbody text', NOTE, guardRef);
    await waitFor(() => expect(guardRef.current).not.toBeNull());
    act(() => guardRef.current!.reload(E2, '# Plan\n\nbody text\n\n> photo text'));
    expect(title()).toHaveValue('Plan');
    await waitFor(() => expect(getMarkdown(getEditor()!)).toContain('photo text'));
    expect(getMarkdown(getEditor()!)).not.toContain('# Plan');
    fireEvent.change(title(), { target: { value: 'Plan B' } });
    fireEvent.blur(title());
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith('# Plan B\n\nbody text\n\n> photo text', E2),
    );
  });

  it('focus mode keeps the title but hides the breadcrumb and byline', () => {
    setup('# Plan\n\nbody text', { ...NOTE, byline: <span>byline here</span> }, undefined, { focus: true });
    expect(title()).toHaveValue('Plan');
    expect(screen.queryByRole('navigation', { name: 'breadcrumb' })).toBeNull();
    expect(screen.queryByText('byline here')).toBeNull();
  });

  it('read-only pages have a read-only title', () => {
    setup('# Plan\n\nbody text', NOTE, undefined, { readOnly: true });
    expect(title()).toHaveAttribute('readonly');
  });

  it('without page there is no title field', () => {
    setup('# Plan\n\nbody text', undefined);
    expect(screen.queryByLabelText('page title')).toBeNull();
  });
});
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/GuardedNoteEditor-page.test.tsx`
Expected: FAIL. `PageChrome` is not exported, there is no `page title` element, and `reload` is not a function.

- [ ] **Step 3: Implement**

Create `desktop/src/renderer/components/page/PageTitle.tsx`:

```tsx
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { sanitizePageTitle } from '../../lib/editor/page-title';

interface Props {
  /** Current title (or the fallback shown when the body owns none). */
  value: string;
  placeholder?: string;
  readOnly?: boolean;
  /** Same debounce as the body autosave. */
  debounceMs?: number;
  /** Called with a sanitised, non-empty, changed title. */
  onCommit: (title: string) => void;
  /** Enter: after committing, move into the page. */
  onEnter?: () => void;
}

/** The page's big editable title. Single line (pasted breaks become spaces),
 * wraps visually; saves on the body's debounce and at once on blur/Enter. */
export function PageTitle({
  value,
  placeholder = 'Untitled',
  readOnly = false,
  debounceMs = 1000,
  onCommit,
  onEnter,
}: Props) {
  const [draft, setDraft] = useState(value);
  const committed = useRef(value);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);

  // Grow with the text so long titles wrap like Confluence's.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [draft]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const cancelTimer = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };

  const commit = (raw: string): void => {
    cancelTimer();
    const next = sanitizePageTitle(raw);
    if (next === '' || next === committed.current) return;
    committed.current = next;
    onCommit(next);
  };

  return (
    <textarea
      ref={ref}
      aria-label="page title"
      rows={1}
      value={draft}
      placeholder={placeholder}
      readOnly={readOnly}
      spellCheck
      className="gb-page-title"
      onChange={(e) => {
        const next = e.target.value.replace(/\r?\n/g, ' ');
        setDraft(next);
        cancelTimer();
        timer.current = setTimeout(() => commit(next), debounceMs);
      }}
      onBlur={() => {
        commit(draft);
        if (sanitizePageTitle(draft) === '') setDraft(committed.current);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
          e.preventDefault();
          commit(draft);
          onEnter?.();
          return;
        }
        // Only a dirty title owns Esc; a clean one lets the viewer close.
        if (e.key === 'Escape' && draft !== committed.current) {
          e.preventDefault();
          cancelTimer();
          setDraft(committed.current);
        }
      }}
    />
  );
}
```

Create `desktop/src/renderer/components/page/PageHeader.tsx`:

```tsx
import { Lucide } from '../Lucide';

function PageBreadcrumb({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <nav aria-label="breadcrumb" className="mb-3">
      <ol className="flex flex-wrap items-center gap-1 text-12 text-ink-3">
        {items.map((it, i) => (
          <li key={`${i}:${it}`} className="flex items-center gap-1">
            {i > 0 && <Lucide name="chevron-right" size={11} />}
            <span>{it}</span>
          </li>
        ))}
      </ol>
    </nav>
  );
}

interface Props {
  breadcrumb: string[];
  title: React.ReactNode;
  byline?: React.ReactNode;
  /** A4 focus mode: the title alone. */
  focus: boolean;
}

export function PageHeader({ breadcrumb, title, byline, focus }: Props) {
  return (
    <div className="gb-page-header" data-testid="page-header">
      {!focus && <PageBreadcrumb items={breadcrumb} />}
      {title}
      {!focus && byline}
    </div>
  );
}
```

Replace the whole of `desktop/src/renderer/components/GuardedNoteEditor.tsx` with the version below. It is main's file plus the page mode and `reload`. Keep any later main change to this file by re-applying it on top.

```tsx
import { useEffect, useRef, useState } from 'react';
import type { Editor } from '@tiptap/core';
import { useGuardedSave, type SaveTarget } from '../lib/use-guarded-save';
import {
  joinPageTitle,
  retitlePage,
  splitPageTitle,
  type PageTitleSplit,
  type TitleRule,
} from '../lib/editor/page-title';
import { ConflictBanner } from './ConflictBanner';
import { RichMarkdownEditor, type RichMarkdownEditorProps } from './RichMarkdownEditor';
import { PageHeader } from './page/PageHeader';
import { PageTitle } from './page/PageTitle';
import { registerNavigationGuard, type NavigationScope } from '../stores/navigation';

export interface GuardHandle {
  adopt: (etag: string | null, body: string) => void;
  /** True while the conflict banner is up (autosave paused, text unsaved). */
  hasConflict: () => boolean;
  /** Replace the note through `perform` (history restore) between autosaves,
   * then reload the editor with the result. Rejects under a conflict. */
  restore: (perform: () => Promise<{ body: string; etag?: string | null }>) => Promise<void>;
  /** Take a body + etag written outside the editor (extract-photo) and
   * reload the page with it, so the page title is re-read from the body. */
  reload: (etag: string | null, body: string) => void;
}

const DISCARD_PROMPT =
  'This note changed outside the editor and your text is not saved. Discard your text?';

/** Call before navigating away from a guarded editor: true when it is safe to
 * leave (no conflict, or the user agreed to discard their unsaved text). */
export function confirmLeave(guardRef: React.MutableRefObject<GuardHandle | null>): boolean {
  return confirmDiscard(guardRef.current);
}

function confirmDiscard(handle: GuardHandle | null): boolean {
  return !handle?.hasConflict() || window.confirm(DISCARD_PROMPT);
}

/** A7: render the note as a page. The title is a line of the body. */
export interface PageChrome {
  /** How the body holds its title (lib/editor/page-title). */
  titleRule: TitleRule;
  /** Shown when the body owns no title (a note's frontmatter title or file
   * name); '' shows the "Untitled" placeholder. */
  fallbackTitle: string;
  /** Ancestors shown above the title. */
  breadcrumb: string[];
  byline?: React.ReactNode;
}

export interface GuardedNoteEditorProps {
  initialBody: string;
  initialEtag: string | null;
  send: SaveTarget['send'];
  fetchLatest: SaveTarget['fetchLatest'];
  onSaveError?: (err: Error) => void;
  /** Lets the parent hand over an etag produced outside the editor (extract-photo). */
  guardRef?: React.MutableRefObject<GuardHandle | null>;
  /** App navigation that would unmount this editor; guarded (same prompt)
   * while the conflict banner is up. */
  navigationScope?: NavigationScope;
  /** A7 page mode: breadcrumb, editable title, byline. */
  page?: PageChrome;
  editorProps: Omit<RichMarkdownEditorProps, 'markdown' | 'onSave' | 'pageHeader'>;
}

/** Per-mount title/body halves. Saves from either half rejoin them. */
interface LiveDoc {
  nonce: number;
  split: PageTitleSplit | null;
  /** Latest editor markdown (the body below the title). */
  rest: string;
  /** What the editor was mounted with (stable: a changing prop would resync it). */
  mountRest: string;
}

/** RichMarkdownEditor with If-Match autosave and the conflict banner.
 * Parents remount it per note (key=…); initial body/etag are read once. */
export function GuardedNoteEditor({
  initialBody,
  initialEtag,
  send,
  fetchLatest,
  onSaveError,
  guardRef,
  navigationScope,
  page,
  editorProps,
}: GuardedNoteEditorProps) {
  const [doc, setDoc] = useState({ body: initialBody, nonce: 0 });
  // Bumped synchronously on every reload, so a debounced save from the
  // replaced editor instance (scheduled before a restore) is dropped.
  const liveNonce = useRef(0);
  const remount = (body: string) => {
    liveNonce.current += 1;
    setDoc({ body, nonce: liveNonce.current });
  };
  const guard = useGuardedSave(
    { body: initialBody, etag: initialEtag },
    { send, fetchLatest },
    onSaveError,
  );
  const guardLatest = useRef(guard);
  guardLatest.current = guard;
  // One stable handle per mount, so unmount only clears its own registration
  // (a key remount mounts the next editor's handle in the same commit).
  const [handle] = useState<GuardHandle>(() => ({
    adopt: (etag, body) => guardLatest.current.adopt(etag, body),
    hasConflict: () => guardLatest.current.hasConflict(),
    restore: async (perform) => {
      const res = await guardLatest.current.runExclusive(perform);
      remount(res.body);
    },
    reload: (etag, body) => {
      guardLatest.current.adopt(etag, body);
      remount(body);
    },
  }));
  useEffect(() => {
    if (!guardRef) return;
    guardRef.current = handle;
    return () => {
      if (guardRef.current === handle) guardRef.current = null;
    };
  }, [guardRef, handle]);
  const conflictPending = guard.conflict !== null;
  useEffect(() => {
    if (!navigationScope || !conflictPending) return;
    return registerNavigationGuard(navigationScope, () => confirmDiscard(handle));
  }, [navigationScope, conflictPending, handle]);

  const keepTheirs = () => {
    const c = guard.keepTheirs();
    if (c) remount(c.theirs);
  };

  // Split once per mount (initial body, restore, keep theirs, reload).
  const titleRule = page?.titleRule ?? null;
  const live = useRef<LiveDoc | null>(null);
  if (live.current === null || live.current.nonce !== doc.nonce) {
    const split = titleRule ? splitPageTitle(doc.body, titleRule) : null;
    const mountRest = split ? split.rest : doc.body;
    live.current = { nonce: doc.nonce, split, rest: mountRest, mountRest };
  }
  const current = live.current;
  const editorRef = useRef<Editor | null>(null);

  const mountNonce = doc.nonce;
  const commitTitle = (title: string) => {
    if (liveNonce.current !== mountNonce || !current.split) return;
    const next = retitlePage(current.split, title);
    if (!next) return;
    current.split = next;
    guard.save(joinPageTitle(next, current.rest));
  };

  const header =
    page && current.split ? (
      <PageHeader
        breadcrumb={page.breadcrumb}
        byline={page.byline}
        focus={editorProps.focus === true}
        title={
          <PageTitle
            value={current.split.kind ? current.split.title : page.fallbackTitle}
            readOnly={editorProps.readOnly}
            debounceMs={editorProps.debounceMs}
            onCommit={commitTitle}
            onEnter={() => editorRef.current?.commands.focus('start')}
          />
        }
      />
    ) : undefined;

  return (
    <>
      {guard.conflict && (
        <ConflictBanner
          conflict={guard.conflict}
          resolving={guard.resolving}
          onKeepMine={() => void guard.keepMine()}
          onKeepTheirs={keepTheirs}
        />
      )}
      <RichMarkdownEditor
        key={doc.nonce}
        markdown={current.mountRest}
        onSave={(md) => {
          if (liveNonce.current !== mountNonce) return;
          current.rest = md;
          guard.save(current.split ? joinPageTitle(current.split, md) : md);
        }}
        {...editorProps}
        onEditorReady={(e) => {
          editorRef.current = e;
          editorProps.onEditorReady?.(e);
        }}
        pageHeader={header}
      />
    </>
  );
}
```

- [ ] **Step 4: Run the tests**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/GuardedNoteEditor-page.test.tsx src/renderer/__tests__/GuardedNoteEditor.test.tsx src/renderer/__tests__/use-guarded-save.test.tsx && npm run typecheck`
Expected: PASS. The existing `GuardedNoteEditor.test.tsx` passes untouched, which proves non-page mode is unchanged.

- [ ] **Step 5: Commit**

```bash
cd "$A7" && git add desktop/src/renderer/components/page/PageTitle.tsx desktop/src/renderer/components/page/PageHeader.tsx desktop/src/renderer/components/GuardedNoteEditor.tsx desktop/src/renderer/__tests__/GuardedNoteEditor-page.test.tsx
git commit -m "feat(page): editable page title and header saved through the B1 guard; GuardHandle.reload (A7)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Jots screen and note viewer as pages

**Files:**
- Modify: `desktop/src/renderer/screens/jots.tsx`, `desktop/src/renderer/components/NoteView.tsx`
- Test: `desktop/src/renderer/__tests__/jots.test.tsx`, `desktop/src/renderer/__tests__/NoteView.test.tsx`

**Interfaces:**
- Consumes: Task 3 `pageBreadcrumb`, `pageAuthor`, `pageUpdated`, `titleRuleFor`, `PageByline` and the `BacklinksPanel` `open`/`onOpenChange` props; Task 7 `GuardedNoteEditor` `page` and `GuardHandle.reload`.
- Produces: both surfaces render as pages. History lives in the byline (it is removed from the jots `TopBar` and the viewer header). Backlinks start collapsed and open from the byline. The viewer header keeps only the synced pill, focus, open in editor and close. The jots footer drops its context pill. Extract-photo uses `guardRef.current?.reload(...)` instead of `adopt` + `replaceWith`.

- [ ] **Step 1: Update and add the failing tests**

`desktop/src/renderer/__tests__/jots.test.tsx`:

(a) Add `within` to the Testing Library import:

```ts
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react';
```

(b) In `it('renders the tree and loads the first jot on select', …)`, replace

```ts
    const leaf = await screen.findByText('first jot');
```

with

```ts
    // The page title (a textarea) also reads "first jot" once the jot loads;
    // the tree leaf comes first in the DOM.
    const leaf = (await screen.findAllByText('first jot'))[0]!;
```

(c) In `it('shows backlinks under the selected jot', …)`, right after the `await waitFor(() => expect(screen.getByText(/full body here/))…)` line, add:

```ts
    // A7: backlinks start collapsed; the byline opens them.
    fireEvent.click(await screen.findByRole('button', { name: '1 backlink' }));
```

(d) Append inside `describe('JotsScreen', …)`:

```ts
  it('shows the jot as a page: breadcrumb, first-line title, byline with history', async () => {
    apiRequest.mockImplementation(withConnectors(async (_m, path) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: page };
      return { ok: true, status: 200, data: detail };
    }));
    render(withQuery(<JotsScreen />));
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());
    expect(screen.getByLabelText('page title')).toHaveValue('first jot');
    const crumbs = screen.getByRole('navigation', { name: 'breadcrumb' });
    expect(within(crumbs).getByText('work')).toBeInTheDocument();
    const byline = screen.getByTestId('page-byline');
    expect(within(byline).getByText('you')).toBeInTheDocument();
    expect(within(byline).getByRole('button', { name: 'history' })).toBeInTheDocument();
  });

  it('renaming the jot rewrites its first line through the jot save', async () => {
    apiRequest.mockImplementation(withConnectors(async (_m, path) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: page };
      return { ok: true, status: 200, data: detail };
    }));
    render(withQuery(<JotsScreen />));
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('page title'), { target: { value: 'Sprint retro' } });
    fireEvent.blur(screen.getByLabelText('page title'));
    await waitFor(() => {
      const call = apiRequest.mock.calls.find(
        ([m, p]) => m === 'PATCH' && p === '/v1/notes/manual-20260514T093015-a',
      );
      expect(call?.[2]).toEqual({ body: 'Sprint retro\n\nfull body here' });
    });
  });
```

`desktop/src/renderer/__tests__/NoteView.test.tsx`:

(a) Add `within` to the Testing Library import.

(b) In `it('shows backlinks for the open note and opens one on click', …)`, replace

```ts
    expect(await screen.findByText('Standup')).toBeInTheDocument();
```

with

```ts
    // A7: backlinks start collapsed; the byline opens them.
    fireEvent.click(await screen.findByRole('button', { name: '1 backlink' }));
    expect(await screen.findByText('Standup')).toBeInTheDocument();
```

(c) Append inside `describe('NoteView', …)`:

```ts
  it('renders a vault note as a page: breadcrumb, H1 title, byline', async () => {
    apiRequest.mockImplementation(async (_m: string, p: string) =>
      p.startsWith('/v1/vault/backlinks')
        ? { ok: true, data: { items: [], indexing: false } }
        : { ok: true, data: syncedNote },
    );
    render(withQuery(<NoteView />));
    act(() => useNoteView.getState().open(syncedNote.path));
    await screen.findByText('from gmail');
    expect(screen.getByLabelText('page title')).toHaveValue('synced');
    const crumbs = screen.getByRole('navigation', { name: 'breadcrumb' });
    expect(within(crumbs).getByText('work')).toBeInTheDocument();
    expect(within(screen.getByTestId('page-byline')).getByText('gmail')).toBeInTheDocument();
    expect(within(screen.getByTestId('page-byline')).getByRole('button', { name: 'history' })).toBeInTheDocument();
  });

  it('renaming the title saves the new H1 through PATCH /v1/notes/body', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: syncedNote });
    render(withQuery(<NoteView />));
    act(() => useNoteView.getState().open(syncedNote.path));
    await screen.findByText('from gmail');
    fireEvent.change(screen.getByLabelText('page title'), { target: { value: 'synced v2' } });
    fireEvent.blur(screen.getByLabelText('page title'));
    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith('PATCH', '/v1/notes/body', {
        path: syncedNote.path,
        body: '# synced v2\n\nfrom gmail',
      }),
    );
  });

  it('Esc in an open insert menu does not close the viewer', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: manualNote });
    render(withQuery(<NoteView />));
    act(() => useNoteView.getState().open(manualNote.path));
    fireEvent.click(await screen.findByRole('button', { name: 'insert' }));
    fireEvent.keyDown(screen.getAllByRole('menuitem')[0]!, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    expect(useNoteView.getState().path).toBe(manualNote.path);
  });
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/jots.test.tsx src/renderer/__tests__/NoteView.test.tsx`
Expected: FAIL. There is no `page title`, no breadcrumb, no byline and no `1 backlink` button.

- [ ] **Step 3: Implement**

`desktop/src/renderer/screens/jots.tsx`:

(a) Imports: delete `import { NoteHistoryButton } from '../components/NoteHistory';` and add:

```ts
import { PageByline } from '../components/page/PageByline';
import { pageAuthor, pageBreadcrumb } from '../lib/page-meta';
```

(b) After `const [cameraSignal, setCameraSignal] = useState(0);` add:

```ts
  // A7: backlinks recede — collapsed until the byline (or their header) opens them.
  const [backlinksOpen, setBacklinksOpen] = useState(false);
  const backlinksRef = useRef<HTMLDivElement | null>(null);
  const showBacklinks = () => {
    setBacklinksOpen(true);
    backlinksRef.current?.scrollIntoView?.({ block: 'nearest' });
  };
```

(c) In the `TopBar` `right` slot, delete:

```tsx
              {selectedItem && (
                <NoteHistoryButton key={selectedItem.path} path={selectedItem.path} guardRef={guardRef} />
              )}
```

(d) In `onPhotoInserted` → `onSuccess`, replace

```ts
                            if (selectedIdRef.current === jotId) {
                              guardRef.current?.adopt(res.etag ?? null, res.body);
                              editorHandle.current?.replaceWith(res.body, 'doc');
                            }
```

with

```ts
                            // reload, not replaceWith: res.body is the whole
                            // note, title line included (A7 page title).
                            if (selectedIdRef.current === jotId) {
                              guardRef.current?.reload(res.etag ?? null, res.body);
                            }
```

(e) On `<GuardedNoteEditor … navigationScope="screen"`, add the `page` prop before `editorProps`:

```tsx
                  page={{
                    titleRule: 'jot',
                    fallbackTitle: '',
                    breadcrumb: selectedItem
                      ? pageBreadcrumb(selectedItem.path, {
                          context: selectedItem.context,
                          project: selectedItem.project ?? null,
                        })
                      : [],
                    byline: selectedItem ? (
                      <PageByline
                        author={pageAuthor({ source: 'manual' })}
                        updated={selectedItem.updated || null}
                        path={selectedItem.path}
                        guardRef={guardRef}
                        onShowBacklinks={showBacklinks}
                      />
                    ) : undefined,
                  }}
```

(f) Replace

```tsx
              {selectedItem && !focusActive && (
                <BacklinksPanel path={selectedItem.path} onOpen={openNote} />
              )}
```

with

```tsx
              {selectedItem && !focusActive && (
                <div ref={backlinksRef}>
                  <BacklinksPanel
                    path={selectedItem.path}
                    onOpen={openNote}
                    open={backlinksOpen}
                    onOpenChange={setBacklinksOpen}
                  />
                </div>
              )}
```

(g) In the footer, delete the context pill (the breadcrumb shows it now):

```tsx
                  {selectedItem?.context && (
                    <Pill>
                      {selectedItem.context}
                      {selectedItem.project ? ` / ${selectedItem.project}` : ''}
                    </Pill>
                  )}
```

`desktop/src/renderer/components/NoteView.tsx`:

(a) Imports: change `import { useEffect, useRef } from 'react';` to `import { useEffect, useRef, useState } from 'react';`, delete `import { NoteHistoryButton } from './NoteHistory';`, and add:

```ts
import { PageByline } from './page/PageByline';
import { pageAuthor, pageBreadcrumb, pageUpdated, titleRuleFor } from '../lib/page-meta';
```

(b) After `const updateNote = useUpdateNoteByPath();` (before any early return) add:

```ts
  // A7: backlinks recede — collapsed until the byline (or their header) opens them.
  const [backlinksOpen, setBacklinksOpen] = useState(false);
  const backlinksRef = useRef<HTMLDivElement | null>(null);
```

(c) After `const isSynced = …;` add:

```ts
  const fm = note.data?.frontmatter;
  const titleRule = titleRuleFor(fm);
  const showBacklinks = () => {
    setBacklinksOpen(true);
    backlinksRef.current?.scrollIntoView?.({ block: 'nearest' });
  };
```

(d) Replace the start of the non-focus header, from `<header className="flex items-center gap-3 border-b border-hairline px-6 py-4">` through `<NoteHistoryButton key={path} path={path} guardRef={guardRef} />`, with

```tsx
          <header className="flex items-center justify-end gap-2 border-b border-hairline px-4 py-2">
            {isSynced && (
              <Pill tone="oxblood">
                synced note — edits may be overwritten by the next sync
              </Pill>
            )}
```

Keep the focus, "open in editor" and close buttons that follow, unchanged. The title and path move into the page (title and breadcrumb).

(e) On `<GuardedNoteEditor … navigationScope="note"`, add before `editorProps`:

```tsx
                  page={{
                    titleRule,
                    fallbackTitle: titleRule === 'note' ? (note.data?.title ?? '') : '',
                    breadcrumb: pageBreadcrumb(path, fm),
                    byline: (
                      <PageByline
                        author={pageAuthor(fm)}
                        updated={pageUpdated(fm)}
                        path={path}
                        guardRef={guardRef}
                        onShowBacklinks={showBacklinks}
                      />
                    ),
                  }}
```

(f) Replace `{!focusActive && <BacklinksPanel path={path} onOpen={openView} />}` with:

```tsx
              {!focusActive && (
                <div ref={backlinksRef}>
                  <BacklinksPanel
                    path={path}
                    onOpen={openView}
                    open={backlinksOpen}
                    onOpenChange={setBacklinksOpen}
                  />
                </div>
              )}
```

- [ ] **Step 4: Run the screen tests, then every gate**

Run: `cd "$A7/desktop" && npx vitest run src/renderer/__tests__/jots.test.tsx src/renderer/__tests__/NoteView.test.tsx`
Expected: PASS, including the unchanged focus-mode tests: in focus mode the byline (and its `history`), the backlinks and the toolbar are gone, and leaving focus mode brings them back.

Then run the full gates: `cd "$A7/desktop" && npm run typecheck && npx vitest run && npm run lint`
Expected: all PASS with zero lint warnings. If another suite fails because a one-line jot body now shows as the title, update that test to read `getByLabelText('page title')` with `toHaveValue(…)`. Do not change the title rule.

- [ ] **Step 5: Manual check (dev build, a throwaway vault, never `~/ghostbrain`)**

1. Jots: the page shows breadcrumb, title, byline and body in a centred column. Rename the title and check that the tree updates within about 5 s. The file's first line changed and nothing else.
2. Toolbar: each tooltip shows its shortcut. Insert → each panel, Expand, Status (its popover opens), Table of contents, Mermaid diagram, Image (file picker), Photo (webcam), Table, Divider, Code block and Quote each insert their block.
3. Click ↔: the column goes full width, and the setting is remembered after a restart.
4. ⌘. (focus): only the FocusBar, the title and the body remain. Esc leaves focus. In the viewer, Esc inside an open Insert menu closes only the menu.
5. Light theme: title, breadcrumb, byline and toolbar are all readable.
6. History (byline) → restore an older version → the title shows that version's title, with no duplicate line in the body.

- [ ] **Step 6: Commit**

```bash
cd "$A7" && git add desktop/src/renderer/screens/jots.tsx desktop/src/renderer/components/NoteView.tsx desktop/src/renderer/__tests__/jots.test.tsx desktop/src/renderer/__tests__/NoteView.test.tsx
git commit -m "feat(jots,notes): render jots and vault notes as confluence-style pages (A7)

Breadcrumb, editable title, byline with history and backlinks; backlinks
collapsed by default; extract-photo reloads through the guard so the
title is re-read from the body.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage (A7 design → task):**
- Centred canvas and width toggle, global and justified → Task 1 (setting), Task 5 (toggle), Task 6 (canvas + CSS).
- Big editable title through the existing storage (the body; no frontmatter, no rename path exists) → Task 2 (model), Task 7 (component + guard), Task 8 (both surfaces).
- Breadcrumb and byline (author, relative updated, History, Backlinks) → Task 3 (helpers + byline), Task 7 (header), Task 8 (wiring, backlinks open from the byline).
- Fixed toolbar: text style, B/I/S/code, lists, link, table, Insert with every block, Template feature-check, Ask AI hook, shortcuts in tooltips, replaces `EditorToolbar` → Tasks 4 and 5. Underline is deliberately omitted (design decision 5) and must be flagged to the user.
- Insert reuses A1's commands → Task 4 `runInsert` over `SLASH_ITEMS`; success and error panels are added there, not duplicated.
- Calmer chrome → Task 8 (history moved, header slimmed, context pill dropped, backlinks collapsed).
- Light/dark tokens → Global Constraints; the Task 6 CSS uses only `var(--…)`. Manual check 5.
- Focus mode consistent with A4 → Task 6 (toolbar hidden, fixed measure), Task 7 (`focus` hides breadcrumb and byline); the existing focus tests still pass in Task 8.
- Both surfaces through `GuardedNoteEditor` (`editorProps` + guard, never bypassed) → Task 7; Task 8 passes `page` only.
- A1 dependency → Global Constraints + Pre-flight.

**Placeholder scan:** no TBD/TODO. Every code step has full code. The two "replace this block" edits (Task 6 JSX, Task 8 screens) quote the exact text to find and the exact text to put in.

**Type consistency:** `PageTitleSplit`/`TitleRule` (Task 2) are used unchanged in Tasks 3 and 7. `PageChrome` and `GuardHandle.reload` are defined in Task 7 and used in Task 8. `EditorToolbarProps` (`onImageFile`, `onAssist`) are defined in Task 5 and used in Task 6. `insertEntries({ canPickImage, canAssist })` matches between Tasks 4 and 5. `BacklinksPanel` `open`/`onOpenChange` match between Tasks 3 and 8. Test ids `page-canvas`, `page-header`, `page-byline`, `image-picker` and the aria names `page title`, `breadcrumb`, `formatting`, `text style`, `insert`, `link`, `link address`, `full width` are used consistently.

**Review Focus:** each of the five items names its pinning test, and that test exists in the owning task's Step 1.
