import CodeBlock from '@tiptap/extension-code-block';
import type { Editor } from '@tiptap/core';
import type { Node as PMNode } from 'prosemirror-model';
import type { NodeView } from '@tiptap/pm/view';
import { emitGb } from './events';
import { renderMermaid } from './mermaid-render';
import { createQueryView } from './query-view';
import { sanitizedDiagramFragment } from './svg-sanitize';

export const MERMAID_TEMPLATE = 'flowchart TD\n  A[Start] --> B[End]';
const RERENDER_DEBOUNCE_MS = 300;

function createPlainCodeView(initial: PMNode, languageClassPrefix: string): NodeView {
  const language = (initial.attrs.language as string | null) ?? null;
  const pre = document.createElement('pre');
  const code = document.createElement('code');
  if (language) code.className = `${languageClassPrefix}${language}`;
  pre.appendChild(code);
  return {
    dom: pre,
    contentDOM: code,
    update: (next) => next.type === initial.type && ((next.attrs.language as string | null) ?? null) === language,
  };
}

function button(label: string, text: string): HTMLButtonElement {
  const b = document.createElement('button');
  b.type = 'button';
  b.setAttribute('aria-label', label);
  b.textContent = text;
  return b;
}

function errorBox(message: string, source: string): HTMLElement {
  const box = document.createElement('div');
  box.className = 'gb-mermaid-error';
  const title = document.createElement('strong');
  title.textContent = `diagram error: ${message}`;
  const pre = document.createElement('pre');
  pre.textContent = source;
  box.append(title, pre);
  return box;
}

function createMermaidView(initial: PMNode, editor: Editor): NodeView {
  let node = initial;
  let editing = node.textContent.trim() === '';
  let timer: ReturnType<typeof setTimeout> | null = null;
  let seq = 0;
  let lastRendered: string | null = null;

  const dom = document.createElement('div');
  dom.className = 'gb-mermaid';
  const bar = document.createElement('div');
  bar.className = 'gb-mermaid-bar';
  bar.contentEditable = 'false';
  const sourceBtn = button('toggle diagram source', 'source');
  const fullBtn = button('open diagram full screen', '⤢');
  bar.append(sourceBtn, fullBtn);
  const preview = document.createElement('div');
  preview.className = 'gb-mermaid-preview';
  preview.contentEditable = 'false';
  const pre = document.createElement('pre');
  const code = document.createElement('code');
  code.className = 'language-mermaid';
  pre.appendChild(code);
  dom.append(bar, preview, pre);

  const applyEditing = (): void => {
    dom.dataset.editing = String(editing);
    sourceBtn.textContent = editing ? 'done' : 'source';
  };

  async function draw(): Promise<void> {
    const source = node.textContent;
    if (source === lastRendered) return;
    lastRendered = source;
    const mine = ++seq;
    const result = await renderMermaid(source);
    if (mine !== seq) return; // a newer render (or destroy) superseded this one
    if (result.ok) {
      // Defence in depth on top of mermaid's securityLevel 'strict': strip links,
      // targets and on* handlers in an inert template before the SVG goes live.
      preview.replaceChildren(sanitizedDiagramFragment(result.svg));
    } else {
      preview.replaceChildren(errorBox(result.error, source));
    }
  }

  const schedule = (delay: number): void => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void draw();
    }, delay);
  };

  sourceBtn.addEventListener('click', (e) => {
    e.preventDefault();
    editing = !editing;
    applyEditing();
  });
  preview.addEventListener('click', () => {
    editing = !editing;
    applyEditing();
  });
  fullBtn.addEventListener('click', (e) => {
    e.preventDefault();
    emitGb(editor, 'gb:diagram:open', { source: node.textContent });
  });

  applyEditing();
  schedule(0);

  return {
    dom,
    contentDOM: code,
    update(next) {
      if (next.type !== node.type || next.attrs.language !== 'mermaid') return false;
      const changed = next.textContent !== node.textContent;
      node = next;
      if (changed) schedule(RERENDER_DEBOUNCE_MS);
      return true;
    },
    stopEvent: (event) => {
      const t = event.target as globalThis.Node | null;
      return !!t && (bar.contains(t) || preview.contains(t));
    },
    ignoreMutation: (mutation) =>
      mutation.type !== 'selection' && !code.contains(mutation.target as globalThis.Node),
    destroy() {
      seq++; // invalidate in-flight renders
      if (timer) clearTimeout(timer);
    },
  };
}

/** StarterKit's codeBlock with per-language node views; markdown handling is
 * tiptap-markdown's default, so every fence round-trips unchanged. */
export const GbCodeBlock = CodeBlock.extend({
  addNodeView() {
    const prefix = this.options.languageClassPrefix;
    return ({ node, editor, getPos }) => {
      const language = (node.attrs.language as string | null) ?? null;
      if (language === 'mermaid') return createMermaidView(node, editor);
      if (language === 'query') return createQueryView(node, editor, getPos);
      return createPlainCodeView(node, prefix);
    };
  },
});
