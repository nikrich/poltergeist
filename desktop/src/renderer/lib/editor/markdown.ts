import type { Editor } from '@tiptap/core';
import { DOMSerializer } from '@tiptap/pm/model';

/** Shape of tiptap-markdown's editor.storage.markdown (set in onBeforeCreate;
 * verified against the 0.8.10 dist source). */
interface MarkdownStorage {
  getMarkdown(): string;
  serializer: { serialize(content: unknown): string };
}

function mdStorage(editor: Editor): MarkdownStorage {
  return editor.storage.markdown as unknown as MarkdownStorage;
}

// prosemirror-markdown escapes "[" / "]" (and emphasis chars adjacent to
// them), which corrupts Obsidian wikilinks: [[a/_b]] → \[\[a/\_b\]\]. Restore
// them after serialisation; the inner unescape only touches backslash-escaped
// punctuation INSIDE the [[...]] span. Intraword underscores, #hashtags and
// bare pipes are not escaped by the serializer (verified) — no handling
// needed outside wikilinks.
const ESCAPED_WIKILINK_RE = /\\\[\\\[(.+?)\\\]\\\]/g;

export function restoreWikilinks(md: string): string {
  return md.replace(
    ESCAPED_WIKILINK_RE,
    (_m, inner: string) => `[[${inner.replace(/\\([\\_*[\]|`~#])/g, '$1')}]]`,
  );
}

/** Serialize the whole document to vault markdown. */
export function getMarkdown(editor: Editor): string {
  return restoreWikilinks(mdStorage(editor).getMarkdown());
}

export interface ClipboardPayload {
  html: string;
  markdown: string;
}

/**
 * Selection-aware payload for copy-formatted (spec: selection if one exists,
 * otherwise the whole note):
 *  - empty selection → whole doc as HTML + markdown;
 *  - otherwise → only the selected slice, HTML via DOMSerializer on the slice
 *    fragment, markdown via tiptap-markdown's serializer on a doc node built
 *    from the slice (falls back to plain text if the slice cannot form a doc).
 */
export function clipboardPayload(editor: Editor): ClipboardPayload {
  if (editor.state.selection.empty) {
    return { html: editor.getHTML(), markdown: getMarkdown(editor) };
  }
  const slice = editor.state.selection.content();
  const container = document.createElement('div');
  container.appendChild(
    DOMSerializer.fromSchema(editor.schema).serializeFragment(slice.content),
  );
  const docNode = editor.schema.topNodeType.createAndFill(null, slice.content);
  const markdown = docNode
    ? restoreWikilinks(mdStorage(editor).serializer.serialize(docNode))
    : editor.state.doc.textBetween(
        editor.state.selection.from,
        editor.state.selection.to,
        '\n',
      );
  return { html: container.innerHTML, markdown };
}
