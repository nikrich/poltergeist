import { Node, mergeAttributes } from '@tiptap/core';
import { Plugin, PluginKey } from '@tiptap/pm/state';
import type { MarkdownSerializerState } from 'prosemirror-markdown';
import type { Node as PMNode } from 'prosemirror-model';
import { emitGb } from './events';

export const STATUS_COLORS = ['grey', 'blue', 'green', 'yellow', 'red', 'purple'] as const;
export type StatusColor = (typeof STATUS_COLORS)[number];

export interface StatusAttrs {
  label: string;
  color: StatusColor | null;
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    status: {
      insertStatus: (attrs: StatusAttrs) => ReturnType;
      updateStatusAt: (pos: number, attrs: Partial<StatusAttrs>) => ReturnType;
    };
  }
}

const PREFIX = 'status:';
const COLOR_SUFFIX_RE = /^([\s\S]*)\/(grey|blue|green|yellow|red|purple)$/;

function isStatusColor(v: unknown): v is StatusColor {
  return typeof v === 'string' && (STATUS_COLORS as readonly string[]).includes(v);
}

export function parseStatusText(text: string): StatusAttrs | null {
  if (!text.startsWith(PREFIX)) return null;
  const body = text.slice(PREFIX.length);
  const m = COLOR_SUFFIX_RE.exec(body);
  const label = m ? m[1]! : body;
  if (label.trim() === '') return null;
  return { label, color: m ? (m[2] as StatusColor) : null };
}

/** CommonMark code span whose fence is longer than any backtick run inside. */
export function codeSpan(text: string): string {
  const longest = Math.max(0, ...(text.match(/`+/g) ?? []).map((run) => run.length));
  const fence = '`'.repeat(longest + 1);
  const pad = text.startsWith('`') || text.endsWith('`') ? ' ' : '';
  return `${fence}${pad}${text}${pad}${fence}`;
}

export function statusMarkdown(attrs: StatusAttrs): string {
  return codeSpan(`${PREFIX}${attrs.label}${attrs.color ? `/${attrs.color}` : ''}`);
}

export function sanitizeStatusLabel(raw: string): string {
  return raw.replace(/\s+/g, ' ').trim();
}

/** parse.updateDOM: inline <code> (not in <pre>) starting with status: → span[data-status]. */
export function replaceStatusCodes(root: HTMLElement): void {
  root.querySelectorAll('code').forEach((code) => {
    if (code.closest('pre')) return;
    const attrs = parseStatusText(code.textContent ?? '');
    if (!attrs) return;
    const span = document.createElement('span');
    span.setAttribute('data-status', '');
    span.setAttribute('data-label', attrs.label);
    if (attrs.color) span.setAttribute('data-color', attrs.color);
    span.textContent = attrs.label;
    code.replaceWith(span);
  });
}

export const Status = Node.create({
  name: 'status',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      label: {
        default: '',
        parseHTML: (el: HTMLElement) => el.getAttribute('data-label') ?? '',
        renderHTML: (a: { label: string }) => ({ 'data-label': a.label }),
      },
      color: {
        default: null,
        parseHTML: (el: HTMLElement) => {
          const v = el.getAttribute('data-color');
          return isStatusColor(v) ? v : null;
        },
        renderHTML: (a: { color: StatusColor | null }) => (a.color ? { 'data-color': a.color } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: 'span[data-status]' }];
  },

  renderHTML({ node, HTMLAttributes }) {
    const color = (node.attrs.color as StatusColor | null) ?? 'grey';
    return [
      'span',
      mergeAttributes(HTMLAttributes, { 'data-status': '', class: `gb-status gb-status-${color}` }),
      node.attrs.label as string,
    ];
  },

  renderText({ node }) {
    return node.attrs.label as string;
  },

  addCommands() {
    return {
      insertStatus:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs }),
      updateStatusAt:
        (pos, attrs) =>
        ({ tr, dispatch }) => {
          const node = tr.doc.nodeAt(pos);
          if (!node || node.type.name !== this.name) return false;
          if (dispatch) tr.setNodeMarkup(pos, undefined, { ...node.attrs, ...attrs });
          return true;
        },
    };
  },

  addProseMirrorPlugins() {
    const editor = this.editor;
    return [
      new Plugin({
        key: new PluginKey('gbStatusClick'),
        props: {
          handleClickOn(_view, _pos, node, nodePos) {
            if (node.type.name !== 'status' || !editor.isEditable) return false;
            emitGb(editor, 'gb:status:edit', { pos: nodePos });
            return true;
          },
        },
      }),
    ];
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: MarkdownSerializerState, node: PMNode) {
          state.write(statusMarkdown(node.attrs as StatusAttrs));
        },
        parse: {
          updateDOM(element: HTMLElement) {
            replaceStatusCodes(element);
          },
        },
      },
    };
  },
});
