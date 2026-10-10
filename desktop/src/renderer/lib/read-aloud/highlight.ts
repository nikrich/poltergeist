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
