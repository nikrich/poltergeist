# Jots Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real WYSIWYG editing experience (toolbar, slash menu, inline images) to Jots and a webcam-capture flow that embeds a photo into the note and writes vision-extracted text beneath it.

**Architecture:** Photos are stored as vault asset files and served to the renderer through a path-guarded `gbasset://` Electron protocol (the renderer can't load `file://` and only reaches the sidecar over IPC). The TipTap editor (single source of truth: `buildEditorExtensions()`) gains a custom inline-image node that stores the vault-relative path but renders via the protocol, plus toolbar/slash UI. A new FastAPI endpoint calls the existing `claude -p` wrapper with the image and appends a markdown blockquote callout that the editor renders as a neon block.

**Tech Stack:** Electron (main + preload), React + TipTap + tiptap-markdown (renderer), Vitest + React Testing Library (desktop tests), FastAPI + Python (sidecar), pytest (sidecar tests), `claude -p` subprocess for vision.

## Global Constraints

- Markdown round-trip is sacred: every editor node must serialize back to plain, portable markdown. New nodes go through `buildEditorExtensions()` in `desktop/src/renderer/lib/editor/extensions.ts` and must be covered by `desktop/src/renderer/__tests__/markdown-roundtrip.test.ts`.
- All LLM calls go through `ghostbrain/llm/client.py:run()` (preserves Claude Max / OAuth billing). Never import the Anthropic SDK.
- IPC handlers follow the existing module pattern: an `installXBridge()` function that calls `ipcMain.removeHandler(channel)` then `ipcMain.handle(channel, …)` and returns `{ ok: true, … }` or `{ ok: false, error: string }`. Register in `desktop/src/main/index.ts`.
- Preload additions go on the `bridge` object in `desktop/src/preload/index.ts` and are typed in `desktop/src/shared/types.ts` (`GbBridge`).
- Vault root in main process: `settings.getAll().vaultPath` (may be empty → handle it). In Python: `ghostbrain.paths.vault_path()`.
- Assets live at vault-relative `90-meta/assets/jots/YYYY/MM/<jotId>-<rand>.<ext>`, referenced from markdown by that vault-relative path (survives the jot moving inbox→context on routing).
- Extracted-text callout markdown shape (verbatim):
  ```
  > **Extracted from photo**
  > <body…>
  ```
- Desktop test command: `cd desktop && npx vitest run <path>`. Typecheck: `cd desktop && npm run typecheck`. Lint: `cd desktop && npm run lint`.
- Sidecar test command: `python -m pytest <path> -v` from repo root.
- Electron version is ≥25: use `protocol.handle` (not the deprecated `registerFileProtocol`).

---

## File Structure

**Slice 1 — Asset infrastructure (main/preload)**
- Create `desktop/src/main/assets.ts` — protocol registration + write IPC + path guard.
- Create `desktop/src/main/__tests__/assets.test.ts`.
- Modify `desktop/src/main/index.ts` — register scheme (top-level), call `registerAssetProtocol()` in `whenReady`, `installAssetBridge()`.
- Modify `desktop/src/preload/index.ts` + `desktop/src/shared/types.ts` — `gb.assets`.
- Modify `desktop/src/renderer/test/setup.ts` — stub `gb.assets`.

**Slice 2 — Inline image node**
- Create `desktop/src/renderer/lib/editor/image.ts` — custom image node.
- Modify `desktop/src/renderer/lib/editor/extensions.ts` — register it.
- Modify `desktop/src/renderer/__tests__/markdown-roundtrip.test.ts` — image fixture.
- Modify `desktop/src/renderer/components/RichMarkdownEditor.tsx` — paste/drop image handler.
- Modify `desktop/package.json` — add `@tiptap/extension-image`.

**Slice 3 — Toolbar + slash menu + input rules**
- Create `desktop/src/renderer/components/EditorToolbar.tsx`.
- Create `desktop/src/renderer/lib/editor/slash.ts` + `desktop/src/renderer/components/SlashMenu.tsx`.
- Modify `RichMarkdownEditor.tsx`, `extensions.ts`, `desktop/package.json` (`@tiptap/suggestion`).

**Slice 4 — Webcam capture**
- Create `desktop/src/renderer/components/WebcamCaptureModal.tsx`.
- Modify `desktop/src/main/index.ts` (`setPermissionRequestHandler`), `desktop/package.json` (`build.mac.extendInfo.NSCameraUsageDescription`).
- Wire the modal into `RichMarkdownEditor`/toolbar/slash and the jots top bar.

**Slice 5 — Vision extraction**
- Modify `ghostbrain/llm/client.py` (image support) + `tests/test_llm_client_image.py`.
- Modify `ghostbrain/api/repo/notes_manual.py` (append callout) + `ghostbrain/api/models/note.py` + `ghostbrain/api/routes/notes.py` + `ghostbrain/api/tests/`.
- Modify `desktop/src/shared/api-types.ts`, `desktop/src/renderer/lib/api/hooks.ts` (extract hook).
- Create `desktop/src/renderer/lib/editor/extract-callout.ts` (TipTap node) + round-trip fixture.

**Slice 6 — Screen polish**
- Modify `desktop/src/renderer/components/JotTree.tsx` (thumbnails), `desktop/src/renderer/screens/jots.tsx` (capture button, wiring).
- Modify `desktop/src/shared/api-types.ts` (`JotListItem.thumbnail`) + `ghostbrain/api/repo/notes_manual.py` (derive first-image path in `list_jots`).

---

## Slice 1 — Asset infrastructure

### Task 1: `gbasset://` protocol + asset write IPC

**Files:**
- Create: `desktop/src/main/assets.ts`
- Create: `desktop/src/main/__tests__/assets.test.ts`
- Modify: `desktop/src/main/index.ts`

**Interfaces:**
- Produces:
  - `registerGbAssetScheme(): void` — call at module top-level before app ready.
  - `registerAssetProtocol(getVaultRoot: () => string): void` — call inside `whenReady`.
  - `installAssetBridge(getVaultRoot: () => string): void` — registers `gb:assets:write`.
  - `assetVaultRelPath(jotId: string, ext: string, rand: string, now: Date): string` — pure helper, returns `90-meta/assets/jots/YYYY/MM/<jotId>-<rand>.<ext>` (forward slashes).
  - `resolveAssetPath(vaultRoot: string, vaultRel: string): string | null` — resolves + path-guards; `null` if it escapes `<vaultRoot>/90-meta/assets`.
  - IPC `gb:assets:write` payload `{ jotId: string; ext: string; bytes: ArrayBuffer | Uint8Array }` → `{ ok: true; path: string } | { ok: false; error: string }`.

- [ ] **Step 1: Write the failing test**

```ts
// desktop/src/main/__tests__/assets.test.ts
import { describe, it, expect } from 'vitest';
import { join } from 'node:path';
import { assetVaultRelPath, resolveAssetPath } from '../assets';

describe('assetVaultRelPath', () => {
  it('builds a dated, slug-safe vault-relative path', () => {
    const p = assetVaultRelPath('abc123def', 'jpg', 'x9z2', new Date('2026-06-24T14:32:00Z'));
    expect(p).toBe('90-meta/assets/jots/2026/06/abc123def-x9z2.jpg');
  });
});

describe('resolveAssetPath', () => {
  const vault = '/vault';
  it('resolves a path inside the asset dir', () => {
    expect(resolveAssetPath(vault, '90-meta/assets/jots/2026/06/a-1.jpg')).toBe(
      join(vault, '90-meta/assets/jots/2026/06/a-1.jpg'),
    );
  });
  it('rejects traversal outside the asset dir', () => {
    expect(resolveAssetPath(vault, '90-meta/assets/../../secrets.md')).toBeNull();
    expect(resolveAssetPath(vault, '../secrets.md')).toBeNull();
    expect(resolveAssetPath(vault, '/etc/passwd')).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/main/__tests__/assets.test.ts`
Expected: FAIL — cannot find module `../assets`.

- [ ] **Step 3: Write minimal implementation**

```ts
// desktop/src/main/assets.ts
import { protocol, net, ipcMain } from 'electron';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, join, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

const ASSET_ROOT_REL = '90-meta/assets/jots';

/** Pure: vault-relative path for a new asset. Forward slashes regardless of OS. */
export function assetVaultRelPath(jotId: string, ext: string, rand: string, now: Date): string {
  const yyyy = String(now.getUTCFullYear());
  const mm = String(now.getUTCMonth() + 1).padStart(2, '0');
  const safeId = jotId.replace(/[^A-Za-z0-9_-]/g, '');
  const safeExt = ext.replace(/[^a-z0-9]/gi, '').toLowerCase() || 'jpg';
  return `${ASSET_ROOT_REL}/${yyyy}/${mm}/${safeId}-${rand}.${safeExt}`;
}

/** Resolve a vault-relative asset path and guard it stays under the asset dir. */
export function resolveAssetPath(vaultRoot: string, vaultRel: string): string | null {
  const assetDir = resolve(vaultRoot, '90-meta', 'assets');
  const candidate = resolve(vaultRoot, vaultRel);
  if (candidate !== assetDir && !candidate.startsWith(assetDir + sep)) return null;
  return candidate;
}

/** Must run before app `whenReady`. */
export function registerGbAssetScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: 'gbasset',
      privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true },
    },
  ]);
}

/** Decode the vault-relative path from a gbasset:// URL. Host is the fixed
 * literal "asset"; the pathname carries the encoded vault-relative path. */
function urlToVaultRel(rawUrl: string): string {
  const u = new URL(rawUrl);
  return decodeURIComponent(u.pathname).replace(/^\/+/, '');
}

export function registerAssetProtocol(getVaultRoot: () => string): void {
  protocol.handle('gbasset', async (request) => {
    const vaultRoot = getVaultRoot();
    if (!vaultRoot) return new Response('vault not configured', { status: 404 });
    const abs = resolveAssetPath(vaultRoot, urlToVaultRel(request.url));
    if (!abs) return new Response('forbidden', { status: 403 });
    try {
      return await net.fetch(pathToFileURL(abs).toString());
    } catch {
      return new Response('not found', { status: 404 });
    }
  });
}

function toBuffer(bytes: unknown): Buffer | null {
  if (bytes instanceof ArrayBuffer) return Buffer.from(bytes);
  if (ArrayBuffer.isView(bytes)) return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return null;
}

function randSuffix(): string {
  return Math.random().toString(36).slice(2, 8);
}

export function installAssetBridge(getVaultRoot: () => string): void {
  ipcMain.removeHandler('gb:assets:write');
  ipcMain.handle('gb:assets:write', async (_e, payload: unknown) => {
    const p = payload as { jotId?: unknown; ext?: unknown; bytes?: unknown };
    if (typeof p?.jotId !== 'string' || typeof p?.ext !== 'string') {
      return { ok: false as const, error: 'assets:write expects { jotId, ext, bytes }' };
    }
    const buf = toBuffer(p.bytes);
    if (!buf) return { ok: false as const, error: 'assets:write: bytes must be ArrayBuffer/TypedArray' };
    const vaultRoot = getVaultRoot();
    if (!vaultRoot) return { ok: false as const, error: 'assets:write: vault not configured' };
    const rel = assetVaultRelPath(p.jotId, p.ext, randSuffix(), new Date());
    const abs = resolveAssetPath(vaultRoot, rel);
    if (!abs) return { ok: false as const, error: 'assets:write: path escaped asset dir' };
    try {
      await mkdir(dirname(abs), { recursive: true });
      await writeFile(abs, buf);
      return { ok: true as const, path: rel };
    } catch (err) {
      return { ok: false as const, error: err instanceof Error ? err.message : String(err) };
    }
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/main/__tests__/assets.test.ts`
Expected: PASS (4 assertions).

- [ ] **Step 5: Wire into the main process**

In `desktop/src/main/index.ts`:
- Add to imports near the other `./` imports:
  ```ts
  import {
    registerGbAssetScheme,
    registerAssetProtocol,
    installAssetBridge,
  } from './assets';
  ```
- Immediately after the imports (top-level, before `app.whenReady`), add:
  ```ts
  // Privileged scheme must be registered before the app is ready.
  registerGbAssetScheme();
  ```
- Add a vault-root getter near `repoRoot()`:
  ```ts
  function vaultRoot(): string {
    return settings.getAll().vaultPath ?? '';
  }
  ```
- Inside `app.whenReady().then(async () => {`, as the first lines of the callback:
  ```ts
  registerAssetProtocol(vaultRoot);
  installAssetBridge(vaultRoot);
  ```

- [ ] **Step 6: Typecheck and commit**

Run: `cd desktop && npm run typecheck`
Expected: passes.

```bash
git add desktop/src/main/assets.ts desktop/src/main/__tests__/assets.test.ts desktop/src/main/index.ts
git commit -m "feat(jots): gbasset:// protocol + asset write IPC"
```

### Task 2: Preload bridge + types for `gb.assets`

**Files:**
- Modify: `desktop/src/preload/index.ts`
- Modify: `desktop/src/shared/types.ts`
- Modify: `desktop/src/renderer/test/setup.ts`

**Interfaces:**
- Produces (renderer-facing):
  - `gb.assets.write(payload: { jotId: string; ext: string; bytes: ArrayBuffer }): Promise<{ ok: true; path: string } | { ok: false; error: string }>`
  - `gb.assets.toUrl(vaultRelPath: string): string` — pure, returns `gbasset://asset/<encoded path>`.

- [ ] **Step 1: Add the type to `GbBridge`**

In `desktop/src/shared/types.ts`, inside the `GbBridge` interface (e.g. right after the `clipboard` block):
```ts
  assets: {
    write(payload: {
      jotId: string;
      ext: string;
      bytes: ArrayBuffer;
    }): Promise<{ ok: true; path: string } | { ok: false; error: string }>;
    toUrl(vaultRelPath: string): string;
  };
```

- [ ] **Step 2: Implement in preload**

In `desktop/src/preload/index.ts`, add to the `bridge` object (after `clipboard`):
```ts
  assets: {
    write: (payload) => ipcRenderer.invoke('gb:assets:write', payload),
    toUrl: (vaultRelPath: string) =>
      'gbasset://asset/' +
      vaultRelPath
        .split('/')
        .map((seg) => encodeURIComponent(seg))
        .join('/'),
  },
```

- [ ] **Step 3: Stub in the renderer test setup**

In `desktop/src/renderer/test/setup.ts`, add to `stubBridge` (next to `clipboard`):
```ts
  assets: {
    write: async () => ({ ok: true as const, path: '90-meta/assets/jots/2026/06/stub-x.jpg' }),
    toUrl: (p: string) => 'gbasset://asset/' + p,
  },
```

- [ ] **Step 4: Typecheck**

Run: `cd desktop && npm run typecheck`
Expected: passes (no type errors in preload/setup).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/preload/index.ts desktop/src/shared/types.ts desktop/src/renderer/test/setup.ts
git commit -m "feat(jots): expose gb.assets bridge (write + toUrl)"
```

---

## Slice 2 — Inline image node

### Task 3: Custom inline-image node with markdown round-trip

**Files:**
- Modify: `desktop/package.json` (add dependency)
- Create: `desktop/src/renderer/lib/editor/image.ts`
- Modify: `desktop/src/renderer/lib/editor/extensions.ts`
- Modify: `desktop/src/renderer/__tests__/markdown-roundtrip.test.ts`

**Interfaces:**
- Consumes: `gb.assets.toUrl` (Task 2), `buildEditorExtensions()` (existing).
- Produces: `JotImage` TipTap node (name `image`) exported from `image.ts`; serializes to `![alt](vaultRelPath)`, parses the same, and renders an `<img>` whose `src` is the gbasset URL while the node attr stays the vault-relative path.

- [ ] **Step 1: Add the dependency**

Run: `cd desktop && npm install @tiptap/extension-image@^2.27.2`
Expected: `package.json` gains `"@tiptap/extension-image": "^2.27.2"`.

- [ ] **Step 2: Write the failing round-trip fixture**

In `desktop/src/renderer/__tests__/markdown-roundtrip.test.ts`, add to the `FIXTURES` object:
```ts
  'inline image': '![whiteboard](90-meta/assets/jots/2026/06/abc-1.jpg)',
  'image among paragraphs':
    'before the shot\n\n![photo](90-meta/assets/jots/2026/06/x-2.jpg)\n\nafter the shot',
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/markdown-roundtrip.test.ts`
Expected: FAIL — image serializes to empty/escaped output (the default StarterKit has no image node, so the markdown is dropped).

- [ ] **Step 4: Implement the node**

```ts
// desktop/src/renderer/lib/editor/image.ts
import Image from '@tiptap/extension-image';

/**
 * Inline-image node for vault notes.
 *
 * The node's `src` attribute always holds the VAULT-RELATIVE path so the
 * markdown stays portable (`![alt](90-meta/assets/…)`). For display only,
 * renderHTML rewrites that path to a `gbasset://` URL the renderer can load.
 * Markdown serialize/parse is wired explicitly for tiptap-markdown.
 */
export const JotImage = Image.extend({
  // Keep the node name "image" so tiptap-markdown's defaults don't double-register.
  renderHTML({ HTMLAttributes }) {
    const src = (HTMLAttributes.src as string) ?? '';
    const display =
      src && !src.startsWith('gbasset://') && !/^https?:/i.test(src)
        ? window.gb.assets.toUrl(src)
        : src;
    return ['img', { ...HTMLAttributes, src: display, class: 'gb-jot-img' }];
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: any, node: any) {
          const alt = (node.attrs.alt ?? '').replace(/([[\]])/g, '\\$1');
          state.write(`![${alt}](${node.attrs.src ?? ''})`);
        },
        parse: {
          // tiptap-markdown's markdown-it already produces `image` tokens;
          // the default tokenizer maps them onto this node by name.
        },
      },
    };
  },
});
```

- [ ] **Step 5: Register the node**

In `desktop/src/renderer/lib/editor/extensions.ts`:
- Add import: `import { JotImage } from './image';`
- Configure StarterKit to not ship its own image (StarterKit v2 has no image node, but be explicit-safe) and add `JotImage` to the returned array, e.g. after `Link.configure(...)`:
  ```ts
    JotImage.configure({ inline: false, allowBase64: false }),
  ```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/markdown-roundtrip.test.ts`
Expected: PASS, including the two new image fixtures.

- [ ] **Step 7: Commit**

```bash
git add desktop/package.json desktop/package-lock.json desktop/src/renderer/lib/editor/image.ts desktop/src/renderer/lib/editor/extensions.ts desktop/src/renderer/__tests__/markdown-roundtrip.test.ts
git commit -m "feat(jots): inline image node with gbasset rendering + md round-trip"
```

### Task 4: Paste / drag-drop image insertion

**Files:**
- Modify: `desktop/src/renderer/components/RichMarkdownEditor.tsx`
- Create: `desktop/src/renderer/lib/editor/insert-image.ts`

**Interfaces:**
- Consumes: `gb.assets.write` (Task 2), `JotImage` node (Task 3).
- Produces: `insertImageFile(editor: Editor, jotId: string, file: File): Promise<void>` — writes the file as an asset and inserts an `image` node at the selection. Accepts a `jotId` prop threaded from the screen.

- [ ] **Step 1: Write the failing test**

```ts
// desktop/src/renderer/__tests__/insert-image.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Editor } from '@tiptap/core';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { getMarkdown } from '../lib/editor/markdown';
import { insertImageFile } from '../lib/editor/insert-image';

beforeEach(() => {
  (window as any).gb = {
    assets: {
      write: vi.fn(async () => ({ ok: true, path: '90-meta/assets/jots/2026/06/j-9.png' })),
      toUrl: (p: string) => 'gbasset://asset/' + p,
    },
  };
});

describe('insertImageFile', () => {
  it('writes the asset and inserts a markdown image at the cursor', async () => {
    const editor = new Editor({ extensions: buildEditorExtensions(), content: 'hello' });
    const file = new File([new Uint8Array([1, 2, 3])], 'shot.png', { type: 'image/png' });
    await insertImageFile(editor, 'jotid123', file);
    expect((window as any).gb.assets.write).toHaveBeenCalledWith(
      expect.objectContaining({ jotId: 'jotid123', ext: 'png' }),
    );
    expect(getMarkdown(editor)).toContain('![](90-meta/assets/jots/2026/06/j-9.png)');
    editor.destroy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/insert-image.test.ts`
Expected: FAIL — cannot find `../lib/editor/insert-image`.

- [ ] **Step 3: Implement**

```ts
// desktop/src/renderer/lib/editor/insert-image.ts
import type { Editor } from '@tiptap/core';

function extFor(file: File): string {
  const fromName = file.name.includes('.') ? file.name.split('.').pop()! : '';
  if (fromName) return fromName.toLowerCase();
  const fromType = file.type.split('/')[1] ?? 'png';
  return fromType.toLowerCase();
}

/** Write a File into the vault and insert an inline image node at the cursor. */
export async function insertImageFile(editor: Editor, jotId: string, file: File): Promise<void> {
  const bytes = await file.arrayBuffer();
  const res = await window.gb.assets.write({ jotId, ext: extFor(file), bytes });
  if (!res.ok) throw new Error(res.error);
  editor.chain().focus().insertContent({ type: 'image', attrs: { src: res.path } }).run();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/insert-image.test.ts`
Expected: PASS.

- [ ] **Step 5: Wire paste/drop into the editor**

In `desktop/src/renderer/components/RichMarkdownEditor.tsx`:
- Add a `jotId: string` prop to `interface Props` and the destructured params.
- Add import: `import { insertImageFile } from '../lib/editor/insert-image';`
- In `useEditor({ … editorProps: { … } })`, add `handlePaste` and `handleDrop` alongside the existing `handleKeyDown`:
  ```ts
      handlePaste: (_view, event) => {
        const files = Array.from(event.clipboardData?.files ?? []).filter((f) =>
          f.type.startsWith('image/'),
        );
        if (files.length === 0 || !editorRef.current) return false;
        event.preventDefault();
        files.forEach((f) => void insertImageFile(editorRef.current!, jotIdRef.current, f).catch((e) => toast.error(`image insert failed: ${e.message}`)));
        return true;
      },
      handleDrop: (_view, event) => {
        const files = Array.from((event as DragEvent).dataTransfer?.files ?? []).filter((f) =>
          f.type.startsWith('image/'),
        );
        if (files.length === 0 || !editorRef.current) return false;
        event.preventDefault();
        files.forEach((f) => void insertImageFile(editorRef.current!, jotIdRef.current, f).catch((e) => toast.error(`image insert failed: ${e.message}`)));
        return true;
      },
  ```
- Because `editorProps` is captured once at creation, route the editor + jotId through refs. Near the top of the component add:
  ```ts
  const editorRef = useRef<Editor | null>(null);
  const jotIdRef = useRef(jotId);
  jotIdRef.current = jotId;
  ```
  and in the existing `useEffect([editor])` that calls `onEditorReady`, also set `editorRef.current = editor;`.
- Pass `jotId` from `jots.tsx` where `<RichMarkdownEditor … />` is rendered: add `jotId={selectedId!}`.

- [ ] **Step 6: Run the editor test suite + typecheck**

Run: `cd desktop && npx vitest run src/renderer/__tests__/RichMarkdownEditor.test.tsx src/renderer/__tests__/insert-image.test.ts && npm run typecheck`
Expected: PASS (update `RichMarkdownEditor.test.tsx` render calls to pass `jotId="test"` if they fail on the new required prop).

- [ ] **Step 7: Commit**

```bash
git add desktop/src/renderer/components/RichMarkdownEditor.tsx desktop/src/renderer/lib/editor/insert-image.ts desktop/src/renderer/__tests__/insert-image.test.ts desktop/src/renderer/screens/jots.tsx desktop/src/renderer/__tests__/RichMarkdownEditor.test.tsx
git commit -m "feat(jots): paste/drop image insertion"
```

---

## Slice 3 — Toolbar, slash menu, input rules

### Task 5: Formatting toolbar

**Files:**
- Create: `desktop/src/renderer/components/EditorToolbar.tsx`
- Create: `desktop/src/renderer/__tests__/EditorToolbar.test.tsx`
- Modify: `desktop/src/renderer/components/RichMarkdownEditor.tsx`

**Interfaces:**
- Consumes: TipTap `Editor`.
- Produces: `<EditorToolbar editor={editor} onPhoto={() => void} />` — renders formatting buttons; reflects active marks via `editor.isActive`.

- [ ] **Step 1: Write the failing test**

```tsx
// desktop/src/renderer/__tests__/EditorToolbar.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Editor } from '@tiptap/core';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { EditorToolbar } from '../components/EditorToolbar';

function makeEditor() {
  return new Editor({ extensions: buildEditorExtensions(), content: 'word' });
}

describe('EditorToolbar', () => {
  it('toggles bold on the current selection', () => {
    const editor = makeEditor();
    editor.commands.selectAll();
    render(<EditorToolbar editor={editor} onPhoto={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /bold/i }));
    expect(editor.isActive('bold')).toBe(true);
    editor.destroy();
  });

  it('invokes onPhoto when the photo button is clicked', () => {
    const editor = makeEditor();
    const onPhoto = vi.fn();
    render(<EditorToolbar editor={editor} onPhoto={onPhoto} />);
    fireEvent.click(screen.getByRole('button', { name: /photo/i }));
    expect(onPhoto).toHaveBeenCalledOnce();
    editor.destroy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/EditorToolbar.test.tsx`
Expected: FAIL — cannot find `../components/EditorToolbar`.

- [ ] **Step 3: Implement**

```tsx
// desktop/src/renderer/components/EditorToolbar.tsx
import { useEffect, useState } from 'react';
import type { Editor } from '@tiptap/core';
import { Lucide } from './Lucide';

interface Props {
  editor: Editor | null;
  onPhoto: () => void;
}

export function EditorToolbar({ editor, onPhoto }: Props) {
  // Re-render on selection/content changes so active states stay accurate.
  const [, force] = useState(0);
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
  const C = editor.chain().focus();

  const items: Array<{ name: string; icon: string; on: () => void; active?: boolean }> = [
    { name: 'bold', icon: 'bold', on: () => C.toggleBold().run(), active: editor.isActive('bold') },
    { name: 'italic', icon: 'italic', on: () => C.toggleItalic().run(), active: editor.isActive('italic') },
    { name: 'heading 1', icon: 'heading-1', on: () => C.toggleHeading({ level: 1 }).run(), active: editor.isActive('heading', { level: 1 }) },
    { name: 'heading 2', icon: 'heading-2', on: () => C.toggleHeading({ level: 2 }).run(), active: editor.isActive('heading', { level: 2 }) },
    { name: 'bullet list', icon: 'list', on: () => C.toggleBulletList().run(), active: editor.isActive('bulletList') },
    { name: 'task list', icon: 'list-checks', on: () => C.toggleTaskList().run(), active: editor.isActive('taskList') },
    { name: 'quote', icon: 'quote', on: () => C.toggleBlockquote().run(), active: editor.isActive('blockquote') },
    { name: 'code', icon: 'code', on: () => C.toggleCode().run(), active: editor.isActive('code') },
  ];

  return (
    <div className="flex flex-shrink-0 items-center gap-1 border-b border-hairline px-2 py-1">
      {items.map((it) => (
        <button
          key={it.name}
          type="button"
          aria-label={it.name}
          onMouseDown={(e) => e.preventDefault()}
          onClick={it.on}
          className={`flex h-6 w-6 items-center justify-center rounded-sm hover:bg-fog ${
            it.active ? 'bg-fog text-ink-0' : 'text-ink-2'
          }`}
        >
          <Lucide name={it.icon} size={13} />
        </button>
      ))}
      <button
        type="button"
        aria-label="photo"
        onMouseDown={(e) => e.preventDefault()}
        onClick={onPhoto}
        className="ml-auto flex items-center gap-1 rounded-sm border border-neon/30 px-2 py-[3px] text-11 text-neon hover:bg-neon-mist"
      >
        <Lucide name="camera" size={12} /> photo
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/EditorToolbar.test.tsx`
Expected: PASS. (If `Lucide` warns on an unknown icon name, pick an existing one from `Lucide.tsx`'s map — verify each icon name renders.)

- [ ] **Step 5: Mount the toolbar in the editor (rich mode only)**

In `RichMarkdownEditor.tsx`, render `<EditorToolbar editor={editor} onPhoto={onPhoto} />` directly above the `mode === 'rich'` `<EditorContent>`. Add an `onPhoto?: () => void` prop (default `() => {}`) — it gets the real handler in Slice 4. Import `EditorToolbar`.

- [ ] **Step 6: Run editor suite + typecheck + commit**

Run: `cd desktop && npx vitest run src/renderer/__tests__/RichMarkdownEditor.test.tsx src/renderer/__tests__/EditorToolbar.test.tsx && npm run typecheck`
Expected: PASS.

```bash
git add desktop/src/renderer/components/EditorToolbar.tsx desktop/src/renderer/__tests__/EditorToolbar.test.tsx desktop/src/renderer/components/RichMarkdownEditor.tsx
git commit -m "feat(jots): formatting toolbar"
```

### Task 6: Slash command menu

**Files:**
- Modify: `desktop/package.json` (add `@tiptap/suggestion`)
- Create: `desktop/src/renderer/lib/editor/slash.ts`
- Create: `desktop/src/renderer/components/SlashMenu.tsx`
- Modify: `desktop/src/renderer/lib/editor/extensions.ts`
- Create: `desktop/src/renderer/__tests__/slash.test.ts`

**Interfaces:**
- Consumes: `buildEditorExtensions()`.
- Produces: `slashCommands` array + `SlashExtension` TipTap extension that, on `/`, shows a filtered menu; selecting an item runs its command. One command `photo` emits a custom editor event `gb:slash:photo` (handled in Slice 4).

- [ ] **Step 1: Add dependency**

Run: `cd desktop && npm install @tiptap/suggestion@^2.27.2`

- [ ] **Step 2: Write the failing test (command list logic)**

```ts
// desktop/src/renderer/__tests__/slash.test.ts
import { describe, it, expect } from 'vitest';
import { filterSlashItems, SLASH_ITEMS } from '../lib/editor/slash';

describe('filterSlashItems', () => {
  it('returns all items for empty query', () => {
    expect(filterSlashItems('')).toHaveLength(SLASH_ITEMS.length);
  });
  it('filters by title prefix, case-insensitive', () => {
    const r = filterSlashItems('head');
    expect(r.every((i) => i.title.toLowerCase().includes('head'))).toBe(true);
    expect(r.length).toBeGreaterThan(0);
  });
  it('matches the photo command on "photo"', () => {
    expect(filterSlashItems('photo').map((i) => i.key)).toContain('photo');
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/slash.test.ts`
Expected: FAIL — cannot find `../lib/editor/slash`.

- [ ] **Step 4: Implement the command list + extension**

```ts
// desktop/src/renderer/lib/editor/slash.ts
import { Extension } from '@tiptap/core';
import type { Editor, Range } from '@tiptap/core';
import Suggestion from '@tiptap/suggestion';

export interface SlashItem {
  key: string;
  title: string;
  run: (editor: Editor, range: Range) => void;
}

export const SLASH_ITEMS: SlashItem[] = [
  { key: 'h1', title: 'Heading 1', run: (e, r) => e.chain().focus().deleteRange(r).setHeading({ level: 1 }).run() },
  { key: 'h2', title: 'Heading 2', run: (e, r) => e.chain().focus().deleteRange(r).setHeading({ level: 2 }).run() },
  { key: 'h3', title: 'Heading 3', run: (e, r) => e.chain().focus().deleteRange(r).setHeading({ level: 3 }).run() },
  { key: 'bullet', title: 'Bullet list', run: (e, r) => e.chain().focus().deleteRange(r).toggleBulletList().run() },
  { key: 'task', title: 'Task list', run: (e, r) => e.chain().focus().deleteRange(r).toggleTaskList().run() },
  { key: 'quote', title: 'Quote', run: (e, r) => e.chain().focus().deleteRange(r).toggleBlockquote().run() },
  { key: 'code', title: 'Code block', run: (e, r) => e.chain().focus().deleteRange(r).toggleCodeBlock().run() },
  { key: 'divider', title: 'Divider', run: (e, r) => e.chain().focus().deleteRange(r).setHorizontalRule().run() },
  { key: 'table', title: 'Table', run: (e, r) => e.chain().focus().deleteRange(r).insertTable({ rows: 2, cols: 2, withHeaderRow: true }).run() },
  { key: 'photo', title: 'Photo (webcam)', run: (e, r) => { e.chain().focus().deleteRange(r).run(); e.emit('gb:slash:photo' as any); } },
];

export function filterSlashItems(query: string): SlashItem[] {
  const q = query.toLowerCase();
  return SLASH_ITEMS.filter((i) => i.title.toLowerCase().includes(q));
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/slash.test.ts`
Expected: PASS.

- [ ] **Step 6: Add the rendering extension + popup**

Append to `slash.ts` a TipTap extension that wires `@tiptap/suggestion` to a React-rendered popup. Implement the popup with a lightweight absolutely-positioned list (no extra dep). Create `SlashMenu.tsx` as the popup component and a `renderSlashPopup()` factory that the Suggestion `render` hook drives (mount/update/destroy a container appended to `document.body`, positioned at `clientRect`). Wire keyboard up/down/enter through the Suggestion `onKeyDown`. Register the extension in `buildEditorExtensions()` (`SlashExtension`).

```ts
// appended to slash.ts
export const SlashExtension = Extension.create({
  name: 'slashCommands',
  addProseMirrorPlugins() {
    return [
      Suggestion({
        editor: this.editor,
        char: '/',
        startOfLine: false,
        command: ({ editor, range, props }) => (props as SlashItem).run(editor, range),
        items: ({ query }) => filterSlashItems(query),
        render: renderSlashPopup,
      }),
    ];
  },
});
```

`renderSlashPopup` returns the `{ onStart, onUpdate, onKeyDown, onExit }` object that creates/positions a `<SlashMenu>` (use `ReactDOM.createRoot` on a body-appended div; position with the `clientRect()` from props; highlight index state held in a closure; Enter calls `props.command(item)`). Keep it under ~70 lines.

- [ ] **Step 7: Register in extensions + manual smoke**

In `extensions.ts`: `import { SlashExtension } from './slash';` and add `SlashExtension` to the returned array. Run the round-trip suite to ensure the new extension didn't change serialization:

Run: `cd desktop && npx vitest run src/renderer/__tests__/markdown-roundtrip.test.ts && npm run typecheck`
Expected: PASS (slash adds no serializable nodes).

- [ ] **Step 8: Commit**

```bash
git add desktop/package.json desktop/package-lock.json desktop/src/renderer/lib/editor/slash.ts desktop/src/renderer/components/SlashMenu.tsx desktop/src/renderer/lib/editor/extensions.ts desktop/src/renderer/__tests__/slash.test.ts
git commit -m "feat(jots): slash command menu"
```

### Task 7: Verify markdown input rules

**Files:**
- Modify: `desktop/src/renderer/__tests__/markdown-roundtrip.test.ts` (add an input-rule behavior test, or a new `editor-input-rules.test.ts`)

**Interfaces:** none new — this task only proves StarterKit's input rules behave (`##`→heading, `-`→bullet, `>`→quote, `[ ]`→task).

- [ ] **Step 1: Write the test**

```ts
// desktop/src/renderer/__tests__/editor-input-rules.test.ts
import { describe, it, expect } from 'vitest';
import { Editor } from '@tiptap/core';
import { buildEditorExtensions } from '../lib/editor/extensions';

function typed(input: string): Editor {
  // Build a doc directly to assert the schema supports these structures;
  // input-rule keystroke simulation is brittle, so assert structural support.
  return new Editor({ extensions: buildEditorExtensions(), content: input });
}

describe('editor schema supports markdown structures', () => {
  it('parses ATX headings', () => {
    expect(typed('## title').getJSON().content?.[0]?.type).toBe('heading');
  });
  it('parses task list items with state', () => {
    const json = typed('- [x] done').getJSON();
    expect(JSON.stringify(json)).toContain('taskItem');
  });
});
```

- [ ] **Step 2: Run it**

Run: `cd desktop && npx vitest run src/renderer/__tests__/editor-input-rules.test.ts`
Expected: PASS (StarterKit + TaskList already provide these). If task items don't appear, ensure `TaskList`/`TaskItem` remain registered in `extensions.ts` (they are).

- [ ] **Step 3: Commit**

```bash
git add desktop/src/renderer/__tests__/editor-input-rules.test.ts
git commit -m "test(jots): pin editor markdown structure support"
```

---

## Slice 4 — Webcam capture

### Task 8: Camera permissions (main) + Info.plist usage string

**Files:**
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/package.json` (`build.mac.extendInfo`)

**Interfaces:**
- Produces: the app session grants `media` permission for its own renderer origin.

- [ ] **Step 1: Add the permission handler**

In `desktop/src/main/index.ts`, add `session` to the electron import and, inside `app.whenReady().then(...)` after `createWindow()`:
```ts
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
    // The renderer is first-party (loaded from our own bundle/dev server);
    // grant camera/mic only, deny everything else.
    callback(permission === 'media');
  });
```

- [ ] **Step 2: Add the macOS usage string**

In `desktop/package.json` under `build.mac`, add:
```json
"extendInfo": { "NSCameraUsageDescription": "Poltergeist uses your camera to capture photos directly into jots." }
```
(If `build.mac` already has an `extendInfo`, merge the key in.)

- [ ] **Step 3: Typecheck + commit**

Run: `cd desktop && npm run typecheck`
Expected: passes.

```bash
git add desktop/src/main/index.ts desktop/package.json
git commit -m "feat(jots): grant camera permission + NSCameraUsageDescription"
```

### Task 9: WebcamCaptureModal component

**Files:**
- Create: `desktop/src/renderer/components/WebcamCaptureModal.tsx`
- Create: `desktop/src/renderer/__tests__/WebcamCaptureModal.test.tsx`

**Interfaces:**
- Consumes: `navigator.mediaDevices` (getUserMedia, enumerateDevices).
- Produces: `<WebcamCaptureModal open onClose onCapture={(file: File) => void} />` — opens the camera, captures a JPEG `File`, stops all tracks on close/unmount/retake.

- [ ] **Step 1: Write the failing test**

```tsx
// desktop/src/renderer/__tests__/WebcamCaptureModal.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WebcamCaptureModal } from '../components/WebcamCaptureModal';

const stop = vi.fn();
beforeEach(() => {
  stop.mockClear();
  const track = { stop, kind: 'video' };
  const stream = { getTracks: () => [track] } as unknown as MediaStream;
  (navigator as any).mediaDevices = {
    getUserMedia: vi.fn(async () => stream),
    enumerateDevices: vi.fn(async () => [
      { kind: 'videoinput', deviceId: 'cam1', label: 'FaceTime HD' },
    ]),
  };
  // jsdom has no canvas encoder; stub toBlob.
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({ drawImage: vi.fn() })) as any;
  HTMLCanvasElement.prototype.toBlob = function (cb: BlobCallback) {
    cb(new Blob([new Uint8Array([1])], { type: 'image/jpeg' }));
  } as any;
});

describe('WebcamCaptureModal', () => {
  it('stops camera tracks when closed', async () => {
    const onClose = vi.fn();
    render(<WebcamCaptureModal open onClose={onClose} onCapture={() => {}} />);
    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: /close|cancel|✕/i }));
    expect(stop).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('emits a jpeg File on capture → use photo', async () => {
    const onCapture = vi.fn();
    render(<WebcamCaptureModal open onClose={() => {}} onCapture={onCapture} />);
    await waitFor(() => expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: /shutter|capture/i }));
    fireEvent.click(await screen.findByRole('button', { name: /use photo/i }));
    await waitFor(() => expect(onCapture).toHaveBeenCalled());
    expect(onCapture.mock.calls[0][0]).toBeInstanceOf(File);
    expect(onCapture.mock.calls[0][0].type).toBe('image/jpeg');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/WebcamCaptureModal.test.tsx`
Expected: FAIL — cannot find component.

- [ ] **Step 3: Implement**

```tsx
// desktop/src/renderer/components/WebcamCaptureModal.tsx
import { useEffect, useRef, useState } from 'react';
import { Btn } from './Btn';
import { Lucide } from './Lucide';

interface Props {
  open: boolean;
  onClose: () => void;
  onCapture: (file: File) => void;
}

type Phase = 'live' | 'review';

export function WebcamCaptureModal({ open, onClose, onCapture }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [phase, setPhase] = useState<Phase>('live');
  const [error, setError] = useState<string | null>(null);

  function stopStream() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }

  async function startStream() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play?.().catch(() => {});
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'camera unavailable');
    }
  }

  useEffect(() => {
    if (!open) return;
    setPhase('live');
    void startStream();
    return () => stopStream();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function handleClose() {
    stopStream();
    onClose();
  }

  function shoot() {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;
    const w = video.videoWidth || 1280;
    const h = video.videoHeight || 720;
    canvas.width = w;
    canvas.height = h;
    canvas.getContext('2d')?.drawImage(video, 0, 0, w, h);
    stopStream(); // freeze: no need to keep the camera on during review
    setPhase('review');
  }

  function usePhoto() {
    canvasRef.current?.toBlob(
      (blob) => {
        if (!blob) return;
        onCapture(new File([blob], `webcam-${Date.now()}.jpg`, { type: 'image/jpeg' }));
        onClose();
      },
      'image/jpeg',
      0.9,
    );
  }

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-[520px] overflow-hidden rounded-lg border border-hairline-2 bg-vellum shadow-float">
        <div className="flex items-center justify-between border-b border-hairline px-4 py-2">
          <span className="text-13 font-semibold">{phase === 'live' ? 'Take a photo' : 'Use this photo?'}</span>
          <button type="button" aria-label="close" onClick={handleClose} className="text-ink-3 hover:text-ink-1">✕</button>
        </div>
        <div className="relative flex h-[280px] items-center justify-center bg-black">
          {error ? (
            <div className="px-6 text-center text-12 text-oxblood">{error}</div>
          ) : (
            <>
              <video ref={videoRef} className={phase === 'live' ? 'h-full' : 'hidden'} muted playsInline />
              <canvas ref={canvasRef} className={phase === 'review' ? 'h-full' : 'hidden'} />
            </>
          )}
        </div>
        <div className="flex items-center gap-2 border-t border-hairline px-4 py-3">
          {phase === 'live' ? (
            <button
              type="button"
              aria-label="shutter"
              disabled={!!error}
              onClick={shoot}
              className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-neon text-paper disabled:opacity-40"
            >
              <Lucide name="camera" size={18} />
            </button>
          ) : (
            <>
              <Btn variant="ghost" size="sm" onClick={() => { setPhase('live'); void startStream(); }}>↺ retake</Btn>
              <Btn variant="primary" size="sm" className="ml-auto" onClick={usePhoto}>use photo →</Btn>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
```
(If `Btn` does not accept `className`, drop that prop and rely on a wrapping `<div className="ml-auto">`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/WebcamCaptureModal.test.tsx`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/components/WebcamCaptureModal.tsx desktop/src/renderer/__tests__/WebcamCaptureModal.test.tsx
git commit -m "feat(jots): webcam capture modal"
```

### Task 10: Wire the modal into the editor + screen

**Files:**
- Modify: `desktop/src/renderer/components/RichMarkdownEditor.tsx`
- Modify: `desktop/src/renderer/screens/jots.tsx`

**Interfaces:**
- Consumes: `WebcamCaptureModal` (Task 9), `insertImageFile` (Task 4), slash `gb:slash:photo` event (Task 6).
- Produces: a working `📷 photo`/`/photo`/top-bar capture path that inserts the image and (Slice 5) triggers extraction via an `onPhotoInserted(path)` callback prop.

- [ ] **Step 1: Open the modal from the editor**

In `RichMarkdownEditor.tsx`:
- Add state `const [camOpen, setCamOpen] = useState(false);`
- Pass `onPhoto={() => setCamOpen(true)}` to `<EditorToolbar>`.
- Subscribe to the slash photo event: in a `useEffect([editor])`, `editor?.on('gb:slash:photo', () => setCamOpen(true))` with matching `off` in cleanup.
- Render at the end of the component:
  ```tsx
  <WebcamCaptureModal
    open={camOpen}
    onClose={() => setCamOpen(false)}
    onCapture={(file) => {
      if (!editorRef.current) return;
      void insertImageFile(editorRef.current, jotIdRef.current, file)
        .then(() => onPhotoInserted?.(jotIdRef.current))
        .catch((e) => toast.error(`photo insert failed: ${e.message}`));
    }}
  />
  ```
- Add prop `onPhotoInserted?: (jotId: string) => void` to `Props`.

- [ ] **Step 2: Add the top-bar capture button**

In `jots.tsx`, add a `📷 capture` `Btn` next to `new` in the `TopBar` `right` slot. Its handler: if no jot is selected, create one (reuse `handleNew`) then open the editor's camera. Simplest deterministic wiring: hold a `const [pendingCapture, setPendingCapture] = useState(false)` and have `RichMarkdownEditor` accept an `openCameraSignal` prop (a number that, when incremented, opens the modal). Increment it on the button click. Add the prop and a `useEffect([openCameraSignal])` in `RichMarkdownEditor` that calls `setCamOpen(true)` when the signal changes (ignore the initial value).

- [ ] **Step 3: Typecheck + run jots/editor suites**

Run: `cd desktop && npm run typecheck && npx vitest run src/renderer/__tests__/jots.test.tsx src/renderer/__tests__/RichMarkdownEditor.test.tsx`
Expected: PASS (adjust test render props for any new required props; all new editor props are optional except `jotId`).

- [ ] **Step 4: Commit**

```bash
git add desktop/src/renderer/components/RichMarkdownEditor.tsx desktop/src/renderer/screens/jots.tsx
git commit -m "feat(jots): open webcam from toolbar, slash, and top bar"
```

---

## Slice 5 — Vision extraction

### Task 11: `llm.client.run` image support

**Files:**
- Modify: `ghostbrain/llm/client.py`
- Create: `tests/test_llm_client_image.py`

**Interfaces:**
- Produces: `run(prompt, *, image_paths: list[str] | None = None, …)` — when `image_paths` is given, the absolute paths are referenced in the prompt so Claude Code reads them.

- [ ] **Step 0: Spike (≤5 min, no code committed)**

Confirm the Claude Code CLI reads an image referenced by absolute path in `--print` mode:
```bash
claude --print --model sonnet "Read the image at $(pwd)/desktop/build/icon.png and reply with one word describing it."
```
Expected: a one-word description (proves Claude reads the file). If instead it needs a different flag, note the exact mechanism and adjust Step 3 accordingly before implementing.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_client_image.py
from unittest.mock import patch
from ghostbrain.llm import client


def test_image_paths_are_referenced_in_command(monkeypatch):
    captured = {}

    def fake_run_once(cmd, *, timeout_s):
        captured["cmd"] = cmd
        return client.LLMResult(text="ok", model="sonnet", structured=None, raw={})

    monkeypatch.setattr(client, "_find_claude_binary", lambda: "/usr/bin/claude")
    monkeypatch.setattr(client, "_run_once", fake_run_once)

    client.run("describe", image_paths=["/abs/photo.jpg"], model="sonnet")

    # The absolute path must appear in the final prompt argument.
    prompt_arg = captured["cmd"][-1]
    assert "/abs/photo.jpg" in prompt_arg
```
(Confirm `LLMResult`'s constructor field names match `client.py`; adjust the `fake_run_once` return to the real dataclass shape.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_client_image.py -v`
Expected: FAIL — `run()` got an unexpected keyword `image_paths`.

- [ ] **Step 3: Implement**

In `ghostbrain/llm/client.py`, add the parameter to `run()`’s signature:
```python
    image_paths: list[str] | None = None,
```
and just before `cmd.append(prompt)` build the effective prompt:
```python
    effective_prompt = prompt
    if image_paths:
        refs = "\n".join(f"- {p}" for p in image_paths)
        effective_prompt = (
            f"{prompt}\n\nRead the following image file(s) and use their contents:\n{refs}"
        )
```
then change `cmd.append(prompt)` to `cmd.append(effective_prompt)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_llm_client_image.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/llm/client.py tests/test_llm_client_image.py
git commit -m "feat(llm): image_paths support in claude -p wrapper"
```

### Task 12: Append-callout repo helper

**Files:**
- Modify: `ghostbrain/api/repo/notes_manual.py`
- Modify: `ghostbrain/api/tests/` (add `test_extract_photo.py` or extend the notes-manual test)

**Interfaces:**
- Consumes: `_find_file`, `read_jot`, `update_jot_body` (existing in `notes_manual.py`), `llm.client.run` (Task 11).
- Produces: `extract_photo_into_jot(jot_id: str, asset_rel_path: str) -> dict` returning `{ "id", "path", "body", "extracted": bool, "reason"?: str }`. Validates `asset_rel_path` is under `90-meta/assets`, calls the vision model, appends the callout, never raises on LLM failure.

- [ ] **Step 1: Write the failing test**

```python
# ghostbrain/api/tests/test_extract_photo.py
from unittest.mock import patch
from ghostbrain.api.repo import notes_manual


def test_extract_appends_callout(tmp_vault):  # tmp_vault: existing fixture creating a vault + inbox jot
    rec = notes_manual.write_inbox_jot("whiteboard shot\n\n")
    asset = "90-meta/assets/jots/2026/06/x-1.jpg"

    class R:  # minimal LLMResult stand-in
        text = "Events flow Kinesis to handler. DLQ on failure."

    with patch.object(notes_manual, "llm_run", return_value=R()):
        out = notes_manual.extract_photo_into_jot(rec["id"], asset)

    assert out["extracted"] is True
    assert "> **Extracted from photo**" in out["body"]
    assert "Events flow Kinesis" in out["body"]


def test_extract_rejects_path_outside_asset_dir(tmp_vault):
    rec = notes_manual.write_inbox_jot("hi\n\n")
    out = notes_manual.extract_photo_into_jot(rec["id"], "../../etc/passwd")
    assert out["extracted"] is False
    assert "asset" in out["reason"].lower()
```
(Match `tmp_vault` to the existing notes test fixtures in `ghostbrain/api/tests/` — reuse whatever fixture those tests use to point `vault_path()` at a temp dir.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest ghostbrain/api/tests/test_extract_photo.py -v`
Expected: FAIL — `extract_photo_into_jot` undefined.

- [ ] **Step 3: Implement**

In `ghostbrain/api/repo/notes_manual.py`:
- Add at imports: `from ghostbrain.llm.client import run as llm_run` and `from ghostbrain.llm.client import LLMError`.
- Add the helper:
```python
_EXTRACT_PROMPT = (
    "Transcribe and concisely summarize the readable content of this image as "
    "plain markdown. No preamble, no surrounding commentary — just the content."
)

def _callout(text: str) -> str:
    body = text.strip() or "(no readable content)"
    quoted = "\n".join(f"> {line}" if line else ">" for line in body.split("\n"))
    return f"> **Extracted from photo**\n{quoted}"

def extract_photo_into_jot(jot_id: str, asset_rel_path: str) -> dict:
    """Run the vision model on an embedded asset and append the result as a
    callout to the jot body. Never raises on LLM failure."""
    abs_asset = _guard_inside_vault(_vault() / asset_rel_path)
    asset_root = (_vault() / "90-meta" / "assets").resolve()
    if asset_root not in abs_asset.parents:
        return {"id": jot_id, "path": "", "body": "", "extracted": False,
                "reason": "asset path outside the asset dir"}
    record = read_jot(jot_id)  # raises JotNotFound if missing
    try:
        result = llm_run(_EXTRACT_PROMPT, image_paths=[str(abs_asset)], model="sonnet")
        text = getattr(result, "text", "") or ""
    except LLMError as e:
        return {"id": jot_id, "path": record["path"], "body": record["body"],
                "extracted": False, "reason": f"vision failed: {e}"}
    new_body = record["body"].rstrip() + "\n\n" + _callout(text) + "\n"
    saved = update_jot_body(jot_id, new_body)
    return {"id": jot_id, "path": saved["path"], "body": new_body, "extracted": True}
```
(Confirm `read_jot` returns a dict with `body` and `path`; it does per `notes_manual.read_jot`. If `_guard_inside_vault` raises on traversal, wrap it in try/except and return the same `extracted: False` shape.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest ghostbrain/api/tests/test_extract_photo.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/notes_manual.py ghostbrain/api/tests/test_extract_photo.py
git commit -m "feat(jots): vision extract → callout repo helper"
```

### Task 13: `POST /v1/notes/{id}/extract-photo` endpoint

**Files:**
- Modify: `ghostbrain/api/models/note.py`
- Modify: `ghostbrain/api/routes/notes.py`
- Modify: `ghostbrain/api/tests/` (route test)

**Interfaces:**
- Consumes: `extract_photo_into_jot` (Task 12).
- Produces: `POST /v1/notes/{jot_id}/extract-photo` body `{ "assetPath": str }` → `{ id, path, body, extracted, reason? }`. 404 for unknown jot; 422 for empty assetPath.

- [ ] **Step 1: Write the failing test**

```python
# ghostbrain/api/tests/test_extract_photo_route.py
from unittest.mock import patch
from fastapi.testclient import TestClient
from ghostbrain.api.main import create_app  # match how other route tests build the app


def test_extract_route_appends(tmp_vault):
    app = create_app()
    client = TestClient(app)
    from ghostbrain.api.repo import notes_manual
    rec = notes_manual.write_inbox_jot("shot\n\n")

    with patch.object(notes_manual, "extract_photo_into_jot",
                      return_value={"id": rec["id"], "path": rec["path"],
                                    "body": "shot\n\n> **Extracted from photo**\n> hi\n",
                                    "extracted": True}):
        r = client.post(f"/v1/notes/{rec['id']}/extract-photo",
                        json={"assetPath": "90-meta/assets/jots/2026/06/x-1.jpg"})
    assert r.status_code == 200
    assert r.json()["extracted"] is True


def test_extract_route_404(tmp_vault):
    app = create_app()
    client = TestClient(app)
    r = client.post("/v1/notes/doesnotexist/extract-photo",
                    json={"assetPath": "90-meta/assets/jots/2026/06/x-1.jpg"})
    assert r.status_code == 404
```
(Match `create_app`/fixture names to the existing route tests under `ghostbrain/api/tests/`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest ghostbrain/api/tests/test_extract_photo_route.py -v`
Expected: FAIL — 404 route not found.

- [ ] **Step 3: Add the request model**

In `ghostbrain/api/models/note.py`, add:
```python
class ExtractPhotoRequest(BaseModel):
    assetPath: str = Field(min_length=1, max_length=500)
```
(Use the same `BaseModel`/`Field` import style already in that file.)

- [ ] **Step 4: Add the route**

In `ghostbrain/api/routes/notes.py`:
- Import `ExtractPhotoRequest` and `extract_photo_into_jot` (+ `JotNotFound` already imported).
- Register BEFORE the `/{jot_id}` catch-all is not required (this has a distinct suffix), but place it next to `route-auto`:
```python
@router.post("/{jot_id}/extract-photo")
def extract_photo(
    req: ExtractPhotoRequest,
    jot_id: str = PathParam(..., min_length=8, max_length=128),
) -> dict:
    """Run the vision model on an embedded photo and append the extracted
    text as a callout. Never 500s on LLM failure (returns extracted=false)."""
    try:
        return extract_photo_into_jot(jot_id, req.assetPath)
    except JotNotFound:
        raise HTTPException(status_code=404, detail=f"Jot not found: {jot_id}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest ghostbrain/api/tests/test_extract_photo_route.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/models/note.py ghostbrain/api/routes/notes.py ghostbrain/api/tests/test_extract_photo_route.py
git commit -m "feat(api): POST /v1/notes/{id}/extract-photo"
```

### Task 14: extract-callout editor node (renders neon block, round-trips)

**Files:**
- Create: `desktop/src/renderer/lib/editor/extract-callout.ts`
- Modify: `desktop/src/renderer/lib/editor/extensions.ts`
- Modify: `desktop/src/renderer/__tests__/markdown-roundtrip.test.ts`

**Interfaces:**
- Produces: a TipTap node that recognizes a blockquote whose first line is `**Extracted from photo**` and renders it with class `gb-extract-callout`; serializes back to the exact callout markdown. If the marker is absent it stays a normal blockquote.

- [ ] **Step 1: Write the failing round-trip fixture**

In `markdown-roundtrip.test.ts` `FIXTURES`:
```ts
  'extract callout':
    '> **Extracted from photo**\n> Events flow Kinesis to handler.\n> DLQ on failure.',
```

- [ ] **Step 2: Run test to verify it fails or passes-as-blockquote**

Run: `cd desktop && npx vitest run src/renderer/__tests__/markdown-roundtrip.test.ts`
Expected: This may already PASS as a plain blockquote (tiptap-markdown round-trips blockquotes). If it passes, the node is purely a rendering concern — keep the fixture as a regression guard and implement Step 3 for the neon styling only. If it FAILS (marker line mangled), Step 3 fixes it.

- [ ] **Step 3: Implement the rendering node**

```ts
// desktop/src/renderer/lib/editor/extract-callout.ts
import Blockquote from '@tiptap/extension-blockquote';

const MARKER = 'Extracted from photo';

/**
 * Renders a blockquote whose first line is the bold marker as a neon callout.
 * Pure presentation: it does NOT change markdown serialization (tiptap-markdown
 * already round-trips blockquotes), so the content stays portable.
 */
export const ExtractCallout = Blockquote.extend({
  renderHTML({ HTMLAttributes, node }) {
    const text = node.firstChild?.textContent ?? '';
    const isCallout = text.startsWith(MARKER);
    const cls = isCallout ? 'gb-extract-callout' : '';
    return ['blockquote', { ...HTMLAttributes, class: cls }, 0];
  },
});
```
- In `extensions.ts`, replace StarterKit's blockquote with this: configure StarterKit `StarterKit.configure({ blockquote: false })` and add `ExtractCallout` to the array. Verify StarterKit accepts disabling blockquote (it does in v2).
- Add the CSS in `desktop/src/renderer/styles.css` (or the gb-prose block):
```css
.gb-extract-callout {
  border-left: 2px solid var(--neon);
  background: var(--neon-mist);
  border-radius: 0 6px 6px 0;
  padding: 7px 12px;
  margin: 8px 0;
}
.gb-extract-callout > p:first-child { color: var(--neon); font-weight: 600; }
```

- [ ] **Step 4: Run round-trip + typecheck**

Run: `cd desktop && npx vitest run src/renderer/__tests__/markdown-roundtrip.test.ts && npm run typecheck`
Expected: PASS, all fixtures including `extract callout` and the existing `blockquote` fixture.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/lib/editor/extract-callout.ts desktop/src/renderer/lib/editor/extensions.ts desktop/src/renderer/__tests__/markdown-roundtrip.test.ts desktop/src/renderer/styles.css
git commit -m "feat(jots): neon extract-callout rendering (md-portable)"
```

### Task 15: Trigger extraction from the renderer

**Files:**
- Modify: `desktop/src/shared/api-types.ts`
- Modify: `desktop/src/renderer/lib/api/hooks.ts`
- Modify: `desktop/src/renderer/components/RichMarkdownEditor.tsx`
- Modify: `desktop/src/renderer/screens/jots.tsx`

**Interfaces:**
- Consumes: `POST /v1/notes/{id}/extract-photo` (Task 13), `onPhotoInserted` (Task 10).
- Produces: `useExtractPhoto()` mutation; on photo insert the screen calls it and shows in-flight/feedback toasts; the jot body refetch surfaces the appended callout.

- [ ] **Step 1: Add types**

In `desktop/src/shared/api-types.ts` (Jots section):
```ts
export interface ExtractPhotoResponse {
  id: string;
  path: string;
  body: string;
  extracted: boolean;
  reason?: string;
}
```

- [ ] **Step 2: Add the hook**

In `desktop/src/renderer/lib/api/hooks.ts` (Jots section), mirroring `useAutoRouteJot`:
```ts
export function useExtractPhoto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jotId, assetPath }: { jotId: string; assetPath: string }) =>
      post<ExtractPhotoResponse>(`/v1/notes/${jotId}/extract-photo`, { assetPath }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: JOTS_KEY });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
    },
  });
}
```
(Import `ExtractPhotoResponse`; match the exact key used by `useJot` for the note-by-path invalidation — check `hooks.ts`.)

- [ ] **Step 3: Thread the asset path out of insert**

Change `insertImageFile` (Task 4) to return the written path:
```ts
export async function insertImageFile(editor: Editor, jotId: string, file: File): Promise<string> {
  // …unchanged…
  return res.path;
}
```
In `RichMarkdownEditor`’s `onCapture`, call `onPhotoInserted?.(jotIdRef.current, path)` with the returned path. Update the `onPhotoInserted` prop type to `(jotId: string, assetPath: string) => void`.

- [ ] **Step 4: Call extraction from the screen**

In `jots.tsx`, instantiate `const extractPhoto = useExtractPhoto();` and pass:
```tsx
onPhotoInserted={(jotId, assetPath) => {
  toast.info('reading photo…');
  extractPhoto.mutate({ jotId, assetPath }, {
    onSuccess: (res) =>
      res.extracted ? toast.success('photo text extracted') : toast.info(`couldn't read photo: ${res.reason ?? ''}`),
    onError: (err) => toast.error(`extract failed: ${err.message}`),
  });
}}
```
to `<RichMarkdownEditor>`.

- [ ] **Step 5: Typecheck + run suites**

Run: `cd desktop && npm run typecheck && npx vitest run src/renderer/__tests__/jots.test.tsx src/renderer/__tests__/insert-image.test.ts`
Expected: PASS (update the `insert-image` test assertion to read the returned path: `const p = await insertImageFile(...); expect(p).toBe('90-meta/assets/jots/2026/06/j-9.png')`).

- [ ] **Step 6: Commit**

```bash
git add desktop/src/shared/api-types.ts desktop/src/renderer/lib/api/hooks.ts desktop/src/renderer/components/RichMarkdownEditor.tsx desktop/src/renderer/screens/jots.tsx desktop/src/renderer/lib/editor/insert-image.ts desktop/src/renderer/__tests__/insert-image.test.ts
git commit -m "feat(jots): trigger vision extraction after photo insert"
```

---

## Slice 6 — Screen polish

### Task 16: Thumbnails in the jot tree

**Files:**
- Modify: `ghostbrain/api/repo/notes_manual.py` (derive first image in `list_jots`)
- Modify: `ghostbrain/api/tests/` (extend list test)
- Modify: `desktop/src/shared/api-types.ts` (`JotListItem.thumbnail`)
- Modify: `desktop/src/renderer/components/JotTree.tsx`

**Interfaces:**
- Produces: `JotListItem.thumbnail: string | null` — vault-relative path of the first embedded image, or null. Tree renders it via `gb.assets.toUrl`.

- [ ] **Step 1: Write the failing backend test**

```python
# extend the existing list_jots test (or add) in ghostbrain/api/tests/
def test_list_jots_includes_first_image_thumbnail(tmp_vault):
    from ghostbrain.api.repo import notes_manual
    notes_manual.write_inbox_jot("see this\n\n![x](90-meta/assets/jots/2026/06/a-1.jpg)\n")
    page = notes_manual.list_jots(limit=10, offset=0)
    item = page["items"][0]
    assert item["thumbnail"] == "90-meta/assets/jots/2026/06/a-1.jpg"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest ghostbrain/api/tests/ -k thumbnail -v`
Expected: FAIL — KeyError `thumbnail`.

- [ ] **Step 3: Implement in `list_jots`**

In `notes_manual.py`, add a pure helper and include it where each list item dict is built:
```python
import re
_IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

def first_image_path(body: str) -> str | None:
    m = _IMG_RE.search(body)
    return m.group(1) if m else None
```
In the item-construction loop in `list_jots`, add `"thumbnail": first_image_path(body)` (use whatever variable already holds the note body there; if only the excerpt is loaded, load `post.content` for the match).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest ghostbrain/api/tests/ -k thumbnail -v`
Expected: PASS.

- [ ] **Step 5: Add the type + render in the tree**

- `api-types.ts`: add `thumbnail: string | null;` to `JotListItem`.
- `JotTree.tsx`: in the leaf button, when `leaf.thumbnail`, render a 28×28 `<img src={window.gb.assets.toUrl(leaf.thumbnail)} className="…rounded-sm…" />` floated right (mirrors mockup A). Keep the title truncation.

- [ ] **Step 6: Typecheck + run tree test**

Run: `cd desktop && npm run typecheck && npx vitest run src/renderer/__tests__/JotTree.test.tsx`
Expected: PASS (add `thumbnail: null` to any `JotListItem` literals in the test fixtures).

- [ ] **Step 7: Commit**

```bash
git add ghostbrain/api/repo/notes_manual.py ghostbrain/api/tests/ desktop/src/shared/api-types.ts desktop/src/renderer/components/JotTree.tsx desktop/src/renderer/__tests__/JotTree.test.tsx
git commit -m "feat(jots): thumbnails in the jot tree"
```

### Task 17: Final polish pass + full-suite green

**Files:**
- Modify: `desktop/src/renderer/screens/jots.tsx`, `desktop/src/renderer/styles.css` (spacing/visual refinements only)

**Interfaces:** none new.

- [ ] **Step 1: Visual refinements**

Apply mockup-A spacing/treatment: ensure the editor toolbar sits flush above the document, the footer keeps the context/routing pills, and the top-bar `capture` button matches the `new` button styling. Add a `.gb-jot-img { max-width: 100%; border-radius: 8px; border: 1px solid var(--hairline-2); margin: 6px 0; }` rule to `styles.css`.

- [ ] **Step 2: Run the full desktop suite + lint + typecheck**

Run: `cd desktop && npm run typecheck && npm run lint && npx vitest run`
Expected: all green. Fix any fixture/prop drift surfaced here.

- [ ] **Step 3: Run the full sidecar suite**

Run: `python -m pytest tests/ ghostbrain/api/tests/ -q`
Expected: all green.

- [ ] **Step 4: Manual smoke (documented, not automated)**

Run the app (`cd desktop && npm run dev` or the project run skill). Verify: create a jot, type `/h1`, toggle bold from the toolbar, hit `📷`, capture a photo, see it embed inline and the neon "Extracted from photo" block fill in. Confirm the `.md` on disk contains `![](90-meta/assets/…)` and the callout blockquote.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/screens/jots.tsx desktop/src/renderer/styles.css
git commit -m "feat(jots): final visual polish"
```

---

## Self-Review

**Spec coverage:**
- Polish (layout A, tree thumbnails, top-bar capture, footer) → Tasks 16, 17, 10.
- Real WYSIWYG: toolbar → Task 5; slash menu → Task 6; markdown input rules → Task 7; inline images → Tasks 3–4.
- Asset infra (`gbasset://`, write IPC, path guard, storage layout) → Tasks 1–2.
- Webcam capture (live/review/insert, permissions, track cleanup) → Tasks 8–10.
- Vision extraction (llm image support, endpoint, callout, in-flight UI) → Tasks 11–15.
- "Embedded in the db = vault asset file" → Tasks 1, 3 (relative path in markdown).
- Error handling (camera denied, asset write fail, extraction never 500s, path traversal) → Tasks 1, 9, 12, 13.
- Testing strategy (protocol guard, round-trip fixtures, modal mocks, backend mocks) → covered per task.

**Out-of-scope items** (galleries, video, batch backfill, base64) are not implemented — correct.

**Type consistency:** `assetVaultRelPath`/`resolveAssetPath` (Task 1) reused by name; `gb.assets.write`/`toUrl` consistent across Tasks 1/2/4/16; `insertImageFile` return type changes to `Promise<string>` in Task 15 with its test updated in the same task; `extract_photo_into_jot` signature consistent Tasks 12/13; `ExtractPhotoResponse` consistent Tasks 13/15; node name `image` kept stable so tiptap-markdown defaults align.

**Known integration points flagged for the implementer:** the Claude CLI image mechanism (Task 11 Step 0 spike); exact existing test-fixture names in `ghostbrain/api/tests/` (Tasks 12, 13, 16); whether `Btn` accepts `className` (Task 9); exact `note-by-path` query key (Task 15).
