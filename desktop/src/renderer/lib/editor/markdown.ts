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
// `\|` is deliberately NOT unescaped: inside a GFM table cell the table
// serializer writes `[[note\|alias]]`, and unescaping it would split the cell.
const ESCAPED_WIKILINK_RE = /\\\[\\\[(.+?)\\\]\\\]/g;

export function restoreWikilinks(md: string): string {
  return md.replace(
    ESCAPED_WIKILINK_RE,
    (_m, inner: string) => `[[${inner.replace(/\\([\\_*[\]`~#])/g, '$1')}]]`,
  );
}

/** Serialize the whole document to vault markdown. */
export function getMarkdown(editor: Editor): string {
  return restoreWikilinks(mdStorage(editor).getMarkdown());
}

/** Markdown for a document range [from, to) — the same slice→doc pattern as
 * clipboardPayload. Falls back to plain text when the slice can't form a doc. */
export function rangeMarkdown(editor: Editor, from: number, to: number): string {
  if (to <= from) return '';
  // includeParents (as selection.content() does): a range inside one paragraph
  // keeps its paragraph wrapper, so the slice can form a doc and keep its marks.
  const slice = editor.state.doc.slice(from, to, true);
  const docNode = editor.schema.topNodeType.createAndFill(null, slice.content);
  if (docNode) return restoreWikilinks(mdStorage(editor).serializer.serialize(docNode));
  return editor.state.doc.textBetween(from, to, '\n');
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
