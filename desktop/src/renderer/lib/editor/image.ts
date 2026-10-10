import Image from '@tiptap/extension-image';
import type { MarkdownSerializerState } from 'prosemirror-markdown';
import type { Node } from 'prosemirror-model';
import { createImageView } from './image-view';

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    gbImage: { setImageWidth: (width: number | null) => ReturnType };
  }
}

const ALT_WIDTH_RE = /^([\s\S]*)\|([1-9]\d{0,4})$/;

/** Obsidian alt-pipe: `alt|480` → { alt: 'alt', width: 480 }. */
export function splitAltWidth(raw: string | null): { alt: string | null; width: number | null } {
  if (raw == null) return { alt: null, width: null };
  const m = ALT_WIDTH_RE.exec(raw);
  return m ? { alt: m[1]!, width: Number(m[2]) } : { alt: raw, width: null };
}

/** Vault-relative path → gbasset:// display URL (http(s) and gbasset pass through). */
export function toDisplaySrc(src: string): string {
  return src && !src.startsWith('gbasset://') && !/^https?:/i.test(src) ? window.gb.assets.toUrl(src) : src;
}

/**
 * Inline-image node for vault notes.
 *
 * The node's `src` attribute always holds the VAULT-RELATIVE path so the
 * markdown stays portable (`![alt|480](90-meta/assets/…)`). For display only,
 * the node view / renderHTML rewrite that path to a `gbasset://` URL.
 */
export const JotImage = Image.extend({
  // Keep the node name "image" so tiptap-markdown's defaults don't double-register.
  addAttributes() {
    return {
      ...this.parent?.(),
      alt: {
        default: null,
        parseHTML: (el: HTMLElement) => splitAltWidth(el.getAttribute('alt')).alt,
      },
      width: {
        default: null,
        parseHTML: (el: HTMLElement) => {
          const fromAlt = splitAltWidth(el.getAttribute('alt')).width;
          if (fromAlt) return fromAlt;
          const attr = Number(el.getAttribute('width'));
          return Number.isInteger(attr) && attr > 0 ? attr : null;
        },
        renderHTML: (a: { width: number | null }) => (a.width ? { width: String(a.width) } : {}),
      },
    };
  },

  renderHTML({ HTMLAttributes }) {
    const src = (HTMLAttributes.src as string) ?? '';
    return ['img', { ...HTMLAttributes, src: toDisplaySrc(src), class: 'gb-jot-img' }];
  },

  addNodeView() {
    return ({ node, editor, getPos }) =>
      createImageView(node, editor, () => (typeof getPos === 'function' ? getPos() : undefined));
  },

  addCommands() {
    return {
      ...this.parent?.(),
      setImageWidth:
        (width) =>
        ({ commands }) =>
          commands.updateAttributes(this.name, { width }),
    };
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: MarkdownSerializerState, node: Node) {
          const alt = (node.attrs.alt ?? '').replace(/([[\]])/g, '\\$1');
          const width = node.attrs.width ? `|${node.attrs.width}` : '';
          state.write(`![${alt}${width}](${node.attrs.src ?? ''})`);
          state.closeBlock(node);
        },
        parse: {
          // markdown-it produces `image` tokens; alt-pipe is split by the
          // alt/width attribute parseHTML above.
        },
      },
    };
  },
});
