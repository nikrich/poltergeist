import { Editor } from '@tiptap/core';
import type { Node as PMNode } from '@tiptap/pm/model';
import { buildEditorExtensions } from '../../lib/editor/extensions';
import { getMarkdown } from '../../lib/editor/markdown';

/** Headless editor built from the exact production schema. */
export function makeEditor(content: string, editable = true): Editor {
  return new Editor({ extensions: buildEditorExtensions(), content, editable });
}

/** Same normalisation as markdown-roundtrip.test.ts: trailing whitespace per line + trailing newlines. */
export function normalizeMd(md: string): string {
  return md
    .split('\n')
    .map((line) => line.replace(/\s+$/, ''))
    .join('\n')
    .replace(/\n+$/, '');
}

export function markdownOf(editor: Editor): string {
  return normalizeMd(getMarkdown(editor));
}

/** Position of the first node matching `test` (document order). Throws if absent. */
export function findNodePos(editor: Editor, test: (n: PMNode) => boolean): number {
  let found = -1;
  editor.state.doc.descendants((node, pos) => {
    if (found !== -1) return false;
    if (test(node)) {
      found = pos;
      return false;
    }
    return true;
  });
  if (found === -1) throw new Error('node not found');
  return found;
}

/** Document position of the first character of `text`. Throws if absent. */
export function textPos(editor: Editor, text: string): number {
  let found = -1;
  editor.state.doc.descendants((node, pos) => {
    if (found !== -1) return false;
    if (node.isText && node.text?.includes(text)) {
      found = pos + node.text.indexOf(text);
      return false;
    }
    return true;
  });
  if (found === -1) throw new Error(`text not found: ${text}`);
  return found;
}
