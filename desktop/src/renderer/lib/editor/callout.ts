import { Node, mergeAttributes } from '@tiptap/core';
import type { MarkdownSerializerState } from 'prosemirror-markdown';
import type { Node as PMNode } from 'prosemirror-model';
import {
  calloutHeader,
  installCalloutRule,
  isCalloutKind,
  isFoldable,
  type CalloutAttrs,
  type MdLike,
} from './callout-format';

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    callout: {
      setCallout: (attrs?: Partial<CalloutAttrs>) => ReturnType;
      toggleCallout: (attrs?: Partial<CalloutAttrs>) => ReturnType;
      unsetCallout: () => ReturnType;
    };
  }
}

function isEmptyBody(node: PMNode): boolean {
  const only = node.childCount === 1 ? node.firstChild : null;
  return !!only && only.isTextblock && only.content.size === 0;
}

const LIST_TYPES = new Set(['bulletList', 'orderedList']);

/**
 * True when `first`, written on the line right after the header, would not
 * start a new block: it would instead continue the header paragraph or turn
 * it into a setext heading, and the callout would be lost on reopen. Those
 * bodies get a blank `>` line after the header. Plain paragraphs stay tight.
 */
function needsBlankAfterHeader(first: PMNode): boolean {
  switch (first.type.name) {
    case 'horizontalRule': // `---` → setext h2 underline
      return true;
    case 'orderedList': // only `1.` may interrupt a paragraph (serializer: start || 1)
      if ((first.attrs.start || 1) !== 1) return true;
      break;
    case 'paragraph': // a line of only `=` → setext h1 underline
      return /^ {0,3}=+[ \t]*(?:\n|$)/.test(first.textContent);
  }
  // An empty list item (`-`, `1.`) cannot interrupt a paragraph; a bare `-`
  // even becomes a setext h2 underline.
  if (LIST_TYPES.has(first.type.name)) {
    const item = first.firstChild?.firstChild;
    return !item || (item.isTextblock && item.content.size === 0);
  }
  return false;
}

export function serializeCallout(state: MarkdownSerializerState, node: PMNode): void {
  const attrs = node.attrs as CalloutAttrs;
  state.wrapBlock('> ', null, node, () => {
    state.write(calloutHeader(attrs));
    if (!isEmptyBody(node)) {
      if (needsBlankAfterHeader(node.firstChild!)) {
        // Blank `>` line between header and body.
        state.ensureNewLine();
        state.write('\n');
      }
      state.ensureNewLine();
      state.renderContent(node);
    }
  });
}

export const Callout = Node.create({
  name: 'callout',
  group: 'block',
  content: 'block+',
  defining: true,

  addAttributes() {
    return {
      kind: {
        default: 'info',
        parseHTML: (el: HTMLElement) => {
          const v = el.getAttribute('data-callout');
          return isCalloutKind(v) ? v : 'info';
        },
        renderHTML: (a: { kind: string }) => ({ 'data-callout': a.kind }),
      },
      title: {
        default: null,
        parseHTML: (el: HTMLElement) => el.getAttribute('data-title') || null,
        renderHTML: (a: { title: string | null }) => (a.title ? { 'data-title': a.title } : {}),
      },
      foldable: {
        default: 'none',
        parseHTML: (el: HTMLElement) => {
          const v = el.getAttribute('data-foldable');
          return isFoldable(v) ? v : 'none';
        },
        renderHTML: (a: { foldable: string }) => ({ 'data-foldable': a.foldable }),
      },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'blockquote[data-callout]',
        priority: 60, // beats ExtractCallout's plain `blockquote` rule (50)
        contentElement: (el: HTMLElement) =>
          (el.querySelector(':scope > .gb-callout-body') as HTMLElement | null) ?? el,
      },
    ];
  },

  renderHTML({ node, HTMLAttributes }) {
    // Used for getHTML (copy formatted / PDF): show the title above the body.
    const attrs = mergeAttributes(HTMLAttributes, { class: 'gb-callout' });
    const title = (node.attrs as CalloutAttrs).title;
    return title
      ? ['blockquote', attrs, ['p', { class: 'gb-callout-title-html' }, title], ['div', { class: 'gb-callout-body' }, 0]]
      : ['blockquote', attrs, ['div', { class: 'gb-callout-body' }, 0]];
  },

  addCommands() {
    return {
      setCallout:
        (attrs = {}) =>
        ({ commands }) =>
          commands.wrapIn(this.name, attrs),
      toggleCallout:
        (attrs = {}) =>
        ({ commands }) =>
          commands.toggleWrap(this.name, attrs),
      unsetCallout:
        () =>
        ({ commands }) =>
          commands.lift(this.name),
    };
  },

  addStorage() {
    return {
      markdown: {
        serialize: serializeCallout,
        parse: {
          setup(md: MdLike) {
            installCalloutRule(md);
          },
        },
      },
    };
  },
});
