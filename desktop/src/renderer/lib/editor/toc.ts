import { Node } from '@tiptap/core';
import type { Editor } from '@tiptap/core';
import type { MarkdownSerializerState } from 'prosemirror-markdown';
import type { Node as PMNode } from 'prosemirror-model';
import type { NodeView } from '@tiptap/pm/view';
import type { Transaction } from '@tiptap/pm/state';

export interface TocEntry {
  level: number;
  text: string;
  pos: number;
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    toc: { insertToc: () => ReturnType };
  }
}

export function collectHeadings(doc: PMNode): TocEntry[] {
  const out: TocEntry[] = [];
  doc.descendants((node, pos) => {
    if (node.type.name === 'heading') {
      const text = node.textContent.trim();
      if (text) out.push({ level: node.attrs.level as number, text, pos });
      return false;
    }
    return true;
  });
  return out;
}

function isEmptyTocPre(el: HTMLElement): boolean {
  const code = el.querySelector('code');
  return !!code && code.classList.contains('language-toc') && (code.textContent ?? '').trim() === '';
}

function createTocView(editor: Editor): NodeView {
  const dom = document.createElement('nav');
  dom.className = 'gb-toc';
  dom.contentEditable = 'false';
  dom.setAttribute('aria-label', 'table of contents');
  const heading = document.createElement('div');
  heading.className = 'gb-toc-title';
  heading.textContent = 'contents';
  const list = document.createElement('ol');
  list.className = 'gb-toc-list';
  dom.append(heading, list);

  let entries: TocEntry[] = [];
  let lastKey = '';

  const rebuild = (): void => {
    entries = collectHeadings(editor.state.doc);
    const key = JSON.stringify(entries.map((e) => [e.level, e.text]));
    if (key === lastKey) return; // positions refreshed above; DOM unchanged
    lastKey = key;
    list.replaceChildren();
    if (entries.length === 0) {
      const li = document.createElement('li');
      li.className = 'gb-toc-empty';
      li.textContent = 'no headings yet';
      list.appendChild(li);
      return;
    }
    const minLevel = Math.min(...entries.map((e) => e.level));
    entries.forEach((entry, index) => {
      const li = document.createElement('li');
      li.style.paddingLeft = `${(entry.level - minLevel) * 12}px`;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = entry.text;
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const target = entries[index];
        if (!target) return;
        editor.chain().focus().setTextSelection(target.pos + 1).scrollIntoView().run();
        (editor.view.nodeDOM(target.pos) as HTMLElement | null)?.scrollIntoView?.({ block: 'start', behavior: 'smooth' });
      });
      li.appendChild(btn);
      list.appendChild(li);
    });
  };

  const onTransaction = ({ transaction }: { transaction: Transaction }): void => {
    if (transaction.docChanged) rebuild();
  };
  editor.on('transaction', onTransaction);
  rebuild();

  return {
    dom,
    stopEvent: (event) => event.target instanceof HTMLElement && !!event.target.closest('button'),
    ignoreMutation: () => true,
    destroy() {
      editor.off('transaction', onTransaction);
    },
  };
}

export const Toc = Node.create({
  name: 'toc',
  group: 'block',
  atom: true,
  selectable: true,

  parseHTML() {
    return [
      { tag: 'div[data-toc]' },
      {
        tag: 'pre',
        priority: 60, // ahead of codeBlock's `pre` rule; falls through when not an empty toc fence
        getAttrs: (el) => (isEmptyTocPre(el as HTMLElement) ? {} : false),
      },
    ];
  },

  renderHTML() {
    return ['div', { 'data-toc': '', class: 'gb-toc' }];
  },

  addNodeView() {
    return ({ editor }) => createTocView(editor);
  },

  addCommands() {
    return {
      insertToc:
        () =>
        ({ commands }) =>
          commands.insertContent({ type: this.name }),
    };
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: MarkdownSerializerState, node: PMNode) {
          state.write('```toc');
          state.ensureNewLine();
          state.write('```');
          state.closeBlock(node);
        },
        parse: {},
      },
    };
  },
});
