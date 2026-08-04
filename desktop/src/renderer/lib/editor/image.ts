import Image from '@tiptap/extension-image';
import type { MarkdownSerializerState } from 'prosemirror-markdown';
import type { Node } from 'prosemirror-model';

/**
 * Inline-image node for vault notes.
 *
 * The node's `src` attribute always holds the VAULT-RELATIVE path so the
 * markdown stays portable (`![alt](90-meta/assets/…)`). For display only,
 * renderHTML rewrites that path to a `gbasset://` URL the renderer can load.
 * Markdown serialize/parse is wired explicitly for tiptap-markdown.
 */
export const JotImage = Image.extend({
  // Keep the node name "image" so tiptap-markdown's defaults don't double-register.
  renderHTML({ HTMLAttributes }) {
    const src = (HTMLAttributes.src as string) ?? '';
    const display =
      src && !src.startsWith('gbasset://') && !/^https?:/i.test(src)
        ? window.gb.assets.toUrl(src)
        : src;
    return ['img', { ...HTMLAttributes, src: display, class: 'gb-jot-img' }];
  },

  addStorage() {
    return {
      markdown: {
        serialize(state: MarkdownSerializerState, node: Node) {
          const alt = (node.attrs.alt ?? '').replace(/([[\]])/g, '\\$1');
          state.write(`![${alt}](${node.attrs.src ?? ''})`);
          state.closeBlock(node);
        },
        parse: {
          // tiptap-markdown's markdown-it already produces `image` tokens;
          // the default tokenizer maps them onto this node by name.
        },
      },
    };
  },
});
