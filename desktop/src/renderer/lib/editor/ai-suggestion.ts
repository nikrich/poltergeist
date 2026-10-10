import type { Editor } from '@tiptap/core';
import { elementFromString } from '@tiptap/core';
import {
  DOMParser as PMDOMParser,
  DOMSerializer,
  Fragment,
  Slice,
  type Node as PMNode,
  type ResolvedPos,
  type Schema,
} from '@tiptap/pm/model';
import { Plugin, PluginKey, type Transaction } from '@tiptap/pm/state';
import { Decoration, DecorationSet } from '@tiptap/pm/view';
import { closeHistory } from '@tiptap/pm/history';

/**
 * Inline AI's diff (spec A5): the replaced range is decorated as a deletion,
 * the streamed answer as an insertion widget. Decorations only — the document
 * is not modified until accept, which is ONE history-sealed transaction.
 * Positions are ProseMirror positions, so A1's custom nodes (callouts, status
 * lozenges, tables) are never spliced as markdown text. While a suggestion is
 * shown the document is locked (filterTransaction), keeping the range valid
 * and keeping user keystrokes out of the save attributed to the assistant.
 * Registered at runtime, never in buildEditorExtensions (no schema change).
 */
export type SuggestionStatus = 'streaming' | 'ready';
export type SuggestionKey = 'accept' | 'reject';

export interface AiSuggestion {
  from: number;
  to: number;
  text: string;
  status: SuggestionStatus;
  /** Insert a space before the answer (continuing straight after a word). */
  joinWithSpace: boolean;
}

export interface AiSuggestionOptions {
  /** Editor-focused Esc / Tab / Mod-Enter; return true when handled. */
  onKey: (key: SuggestionKey) => boolean;
}

type Action =
  | { type: 'start'; from: number; to: number; joinWithSpace: boolean }
  | { type: 'text'; text: string; status: SuggestionStatus }
  | { type: 'clear' };

export const aiSuggestionKey = new PluginKey<AiSuggestion | null>('gbAiSuggestion');
const ALLOW_META = 'gbAiSuggestionAllow';
export const DEL_CLASS = 'gb-ai-del';
export const DEL_BLOCK_CLASS = 'gb-ai-del-block';
export const INS_CLASS = 'gb-ai-ins';

function clampRange(doc: PMNode, from: number, to: number): { from: number; to: number } {
  const size = doc.content.size;
  const f = Math.max(0, Math.min(from, size));
  return { from: f, to: Math.max(f, Math.min(to, size)) };
}

/** Markdown → schema nodes through the same tiptap-markdown parser (and A1's
 * parse hooks) the editor uses, so callouts/status/etc. come back as nodes. */
export function markdownToFragment(editor: Editor, md: string): Fragment {
  const storage = editor.storage.markdown as { parser: { parse(content: string): string } };
  const html = storage.parser.parse(md);
  return PMDOMParser.fromSchema(editor.schema).parse(elementFromString(html)).content;
}

function singleParagraphInline(frag: Fragment): Fragment | null {
  const only = frag.childCount === 1 ? frag.firstChild : null;
  return only && only.type.name === 'paragraph' && only.content.size > 0 ? only.content : null;
}

/** Text blocks joined by single spaces — what A1's GFM table serializer
 * would write for a multi-block cell anyway. */
function flattenToInline(frag: Fragment, schema: Schema): Fragment {
  const parts: PMNode[] = [];
  const push = (nodes: PMNode[]): void => {
    if (nodes.length === 0) return;
    if (parts.length > 0) parts.push(schema.text(' '));
    parts.push(...nodes);
  };
  frag.descendants((node) => {
    if (!node.isTextblock) return true;
    if (node.type.spec.code) {
      const text = node.textContent.replace(/\s+/g, ' ').trim();
      if (text) push([schema.text(text)]);
      return false;
    }
    const kids: PMNode[] = [];
    node.forEach((child) => kids.push(child.type.name === 'hardBreak' ? schema.text(' ') : child));
    push(kids);
    return false;
  });
  return Fragment.fromArray(parts);
}

function insideCell($pos: ResolvedPos): boolean {
  for (let d = $pos.depth; d > 0; d--) {
    const role = $pos.node(d).type.spec.tableRole as string | undefined;
    if (role === 'cell' || role === 'header_cell') return true;
  }
  return false;
}

function needsSpace(inline: Fragment): boolean {
  const first = inline.firstChild;
  if (!first) return false;
  return !(first.isText && /^[\s.,;:!?)\]]/.test(first.text ?? ''));
}

/** True when the fragment holds anything to insert (text, an atom, a rule,
 * an image) rather than nothing or only empty blocks. */
function hasContent(frag: Fragment): boolean {
  let found = false;
  frag.descendants((node) => {
    if (node.isLeaf) found = true;
    return !found;
  });
  return found;
}

interface Shaped {
  inline: boolean;
  content: Fragment;
}

/** The single source of what an answer becomes at a position, shared by the
 * preview and the accept so the user sees exactly what will be written:
 * one paragraph (or anything inside a table cell, flattened) goes in inline
 * with the joining space; anything else goes in as blocks. Null when the
 * answer holds nothing to insert, so accept never just deletes the range. */
function shapeAnswer(schema: Schema, s: AiSuggestion, frag: Fragment, inCell: boolean): Shaped | null {
  if (!hasContent(frag)) return null;
  const single = singleParagraphInline(frag);
  if (!single && !inCell) return { inline: false, content: frag };
  let inline = single ?? flattenToInline(frag, schema);
  if (!hasContent(inline)) return null;
  if (s.joinWithSpace && needsSpace(inline)) inline = Fragment.from(schema.text(' ')).append(inline);
  return { inline: true, content: inline };
}

function renderInsertion(editor: Editor, s: AiSuggestion, inCell: boolean): HTMLElement {
  const wrap = document.createElement('span');
  wrap.className = INS_CLASS;
  wrap.setAttribute('data-testid', 'ai-insertion');
  wrap.contentEditable = 'false';
  if (!s.text.trim()) {
    wrap.classList.add('gb-ai-pending');
    wrap.textContent = '…';
    return wrap;
  }
  let frag: Fragment;
  try {
    frag = markdownToFragment(editor, s.text);
  } catch {
    wrap.textContent = s.text;
    return wrap;
  }
  const shaped = shapeAnswer(editor.schema, s, frag, inCell);
  if (!shaped) {
    wrap.classList.add('gb-ai-pending');
    wrap.textContent = '…';
    return wrap;
  }
  if (!shaped.inline) wrap.classList.add('gb-ai-ins-block');
  wrap.append(DOMSerializer.fromSchema(editor.schema).serializeFragment(shaped.content));
  return wrap;
}

function buildDecorations(editor: Editor, doc: PMNode, s: AiSuggestion): DecorationSet {
  const decos: Decoration[] = [];
  if (s.to > s.from) {
    decos.push(Decoration.inline(s.from, s.to, { class: DEL_CLASS }));
    doc.nodesBetween(s.from, s.to, (node, pos) => {
      if (node.isBlock && pos >= s.from && pos + node.nodeSize <= s.to) {
        decos.push(Decoration.node(pos, pos + node.nodeSize, { class: DEL_BLOCK_CLASS }));
        return false;
      }
      return true;
    });
  }
  const inCell = insideCell(doc.resolve(s.from));
  decos.push(
    Decoration.widget(s.to, () => renderInsertion(editor, s, inCell), {
      side: 1,
      ignoreSelection: true,
      key: `gb-ai-ins:${s.status}:${s.joinWithSpace ? 1 : 0}:${inCell ? 1 : 0}:${s.text}`,
    }),
  );
  return DecorationSet.create(doc, decos);
}

function aiSuggestionPlugin(editor: Editor, opts: AiSuggestionOptions): Plugin<AiSuggestion | null> {
  return new Plugin<AiSuggestion | null>({
    key: aiSuggestionKey,
    state: {
      init: () => null,
      apply(tr, value) {
        const action = tr.getMeta(aiSuggestionKey) as Action | undefined;
        if (action?.type === 'clear') return null;
        if (action?.type === 'start') {
          const r = clampRange(tr.doc, action.from, action.to);
          return { ...r, text: '', status: 'streaming', joinWithSpace: action.joinWithSpace };
        }
        if (!value) return null;
        let next = value;
        if (tr.docChanged) {
          const from = tr.mapping.map(value.from, 1);
          next = { ...next, from, to: Math.max(from, tr.mapping.map(value.to, -1)) };
        }
        if (action?.type === 'text') next = { ...next, text: action.text, status: action.status };
        return next;
      },
    },
    filterTransaction(tr, state) {
      if (!tr.docChanged || tr.getMeta(ALLOW_META)) return true;
      return aiSuggestionKey.getState(state) === null;
    },
    props: {
      decorations(state) {
        const s = aiSuggestionKey.getState(state);
        return s ? buildDecorations(editor, state.doc, s) : DecorationSet.empty;
      },
      handleKeyDown(view, event) {
        const s = aiSuggestionKey.getState(view.state);
        if (!s) return false;
        if (event.key === 'Escape') return opts.onKey('reject');
        const mod = event.metaKey || event.ctrlKey;
        const acceptKey =
          (event.key === 'Tab' && !event.shiftKey && !mod && !event.altKey) ||
          (event.key === 'Enter' && mod);
        if (!acceptKey) return false;
        // Swallowed while streaming: Tab must not indent a list under the diff.
        return s.status === 'ready' ? opts.onKey('accept') : true;
      },
    },
  });
}

function attached(editor: Editor): boolean {
  return !editor.isDestroyed && aiSuggestionKey.getState(editor.state) !== undefined;
}

/** Registered FIRST so Esc/Tab/Mod-Enter beat list and code keymaps. */
export function attachAiSuggestion(editor: Editor, opts: AiSuggestionOptions): () => void {
  if (editor.isDestroyed || attached(editor)) return () => {};
  editor.registerPlugin(aiSuggestionPlugin(editor, opts), (plugin, plugins) => [plugin, ...plugins]);
  return () => {
    if (attached(editor)) editor.unregisterPlugin(aiSuggestionKey);
  };
}

function send(editor: Editor, action: Action): void {
  if (!attached(editor)) return;
  editor.view.dispatch(editor.state.tr.setMeta(aiSuggestionKey, action).setMeta('addToHistory', false));
}

export function getAiSuggestion(editor: Editor): AiSuggestion | null {
  return attached(editor) ? (aiSuggestionKey.getState(editor.state) ?? null) : null;
}

export function startAiSuggestion(
  editor: Editor,
  range: { from: number; to: number },
  opts: { joinWithSpace?: boolean } = {},
): void {
  send(editor, { type: 'start', from: range.from, to: range.to, joinWithSpace: opts.joinWithSpace ?? false });
}

export function setAiSuggestionText(editor: Editor, text: string, status: SuggestionStatus): void {
  if (getAiSuggestion(editor)) send(editor, { type: 'text', text, status });
}

export function clearAiSuggestion(editor: Editor): void {
  if (getAiSuggestion(editor)) send(editor, { type: 'clear' });
}

function applyReplacement(editor: Editor, s: AiSuggestion, frag: Fragment): Transaction | null {
  const { state, schema } = editor;
  const { from, to } = clampRange(state.doc, s.from, s.to);
  const $from = state.doc.resolve(from);
  const shaped = shapeAnswer(schema, s, frag, insideCell($from));
  if (!shaped) return null;
  try {
    const tr = state.tr;
    if (shaped.inline) {
      tr.replaceWith(from, to, shaped.content);
    } else if (from === to && $from.parent.isTextblock && $from.parent.content.size === 0) {
      tr.replaceWith($from.before(), $from.after(), frag);
    } else {
      tr.replaceRange(from, to, new Slice(frag, 0, 0));
    }
    tr.doc.check();
    if (tr.docChanged) return tr;
  } catch {
    // fall through to plain text
  }
  const plain = frag.textBetween(0, frag.size, ' ', ' ').trim();
  if (!plain) return null;
  try {
    return state.tr.insertText(plain, from, to);
  } catch {
    return null;
  }
}

export function buildAcceptTransaction(editor: Editor, s: AiSuggestion): Transaction | null {
  if (!s.text.trim()) return null;
  let frag: Fragment;
  try {
    frag = markdownToFragment(editor, s.text);
  } catch {
    return null;
  }
  const tr = applyReplacement(editor, s, frag);
  if (!tr || tr.doc.eq(editor.state.doc)) return null;
  closeHistory(tr); // never merge into the user's previous typing
  return tr
    .setMeta(aiSuggestionKey, { type: 'clear' } satisfies Action)
    .setMeta(ALLOW_META, true)
    .scrollIntoView();
}

export function acceptAiSuggestion(editor: Editor): boolean {
  const s = getAiSuggestion(editor);
  if (!s || s.status !== 'ready') return false;
  const tr = buildAcceptTransaction(editor, s);
  if (!tr) {
    clearAiSuggestion(editor);
    return false;
  }
  editor.view.dispatch(tr);
  // Seal the undo group: the next keystroke is its own step (one undo = accept).
  editor.view.dispatch(closeHistory(editor.state.tr));
  return true;
}
