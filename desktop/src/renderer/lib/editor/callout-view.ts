import type { Editor } from '@tiptap/core';
import type { Node as PMNode } from 'prosemirror-model';
import type { NodeView } from '@tiptap/pm/view';
import {
  CALLOUT_KINDS,
  sanitizeCalloutTitle,
  type CalloutAttrs,
  type CalloutFoldable,
  type CalloutKind,
} from './callout-format';

export const CALLOUT_GLYPH: Record<CalloutKind, string> = {
  info: 'i',
  note: '✎',
  tip: '✦',
  warning: '!',
  error: '×',
  success: '✓',
};

export function nextFoldable(f: CalloutFoldable): CalloutFoldable {
  return f === 'closed' ? 'open' : 'closed';
}

export function createCalloutView(
  node: PMNode,
  editor: Editor,
  getPos: () => number | undefined,
): NodeView {
  let current = node;
  // Read-only editors fold visually without writing; null = follow attrs.
  let localCollapsed: boolean | null = null;

  const dom = document.createElement('div');
  dom.className = 'gb-callout';

  const header = document.createElement('div');
  header.className = 'gb-callout-header';
  header.contentEditable = 'false';

  const chevron = document.createElement('button');
  chevron.type = 'button';
  chevron.className = 'gb-callout-chevron';
  chevron.setAttribute('aria-label', 'toggle callout');

  const glyph = document.createElement('span');
  glyph.className = 'gb-callout-glyph';

  const kindSelect = document.createElement('select');
  kindSelect.className = 'gb-callout-kind';
  kindSelect.setAttribute('aria-label', 'callout type');
  for (const k of CALLOUT_KINDS) {
    const opt = document.createElement('option');
    opt.value = k;
    opt.textContent = k;
    kindSelect.appendChild(opt);
  }

  const titleInput = document.createElement('input');
  titleInput.className = 'gb-callout-title';
  titleInput.placeholder = 'title';
  titleInput.setAttribute('aria-label', 'callout title');

  header.append(chevron, glyph, kindSelect, titleInput);

  const body = document.createElement('div');
  body.className = 'gb-callout-body';
  dom.append(header, body);

  function attrs(): CalloutAttrs {
    return current.attrs as CalloutAttrs;
  }

  function setAttrs(patch: Partial<CalloutAttrs>): void {
    const pos = getPos();
    if (typeof pos !== 'number' || !editor.isEditable) return;
    editor.view.dispatch(editor.state.tr.setNodeMarkup(pos, undefined, { ...current.attrs, ...patch }));
  }

  function sync(): void {
    const a = attrs();
    const collapsed = localCollapsed ?? a.foldable === 'closed';
    dom.dataset.kind = a.kind;
    dom.dataset.foldable = a.foldable;
    dom.dataset.collapsed = String(collapsed);
    chevron.hidden = a.foldable === 'none';
    chevron.textContent = collapsed ? '▸' : '▾';
    glyph.textContent = CALLOUT_GLYPH[a.kind];
    kindSelect.value = a.kind;
    kindSelect.disabled = !editor.isEditable;
    titleInput.readOnly = !editor.isEditable;
    if (document.activeElement !== titleInput) titleInput.value = a.title ?? '';
  }

  chevron.addEventListener('click', (e) => {
    e.preventDefault();
    const a = attrs();
    if (a.foldable === 'none') return;
    if (!editor.isEditable) {
      localCollapsed = !(localCollapsed ?? a.foldable === 'closed');
      sync();
      return;
    }
    setAttrs({ foldable: nextFoldable(a.foldable) });
  });

  kindSelect.addEventListener('change', () => {
    setAttrs({ kind: kindSelect.value as CalloutKind });
  });

  const commitTitle = (): void => {
    const next = sanitizeCalloutTitle(titleInput.value);
    if (next !== attrs().title) setAttrs({ title: next });
  };
  titleInput.addEventListener('change', commitTitle);
  titleInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitTitle();
      editor.commands.focus();
    } else if (e.key === 'Escape') {
      // Revert the draft and keep Escape from reaching NoteView's close-note listener.
      e.preventDefault();
      e.stopPropagation();
      titleInput.value = attrs().title ?? '';
      editor.commands.focus();
    }
  });

  sync();

  return {
    dom,
    contentDOM: body,
    update(next) {
      if (next.type !== current.type) return false;
      current = next;
      sync();
      return true;
    },
    stopEvent(event) {
      return header.contains(event.target as globalThis.Node);
    },
    ignoreMutation(mutation) {
      return mutation.type !== 'selection' && !body.contains(mutation.target as globalThis.Node);
    },
  };
}
