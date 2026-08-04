import Blockquote from '@tiptap/extension-blockquote';

const MARKER = 'Extracted from photo';

/**
 * Renders a blockquote whose first line is the bold marker as a neon callout.
 * Pure presentation: it does NOT change markdown serialization (tiptap-markdown
 * already round-trips blockquotes), so the content stays portable.
 */
export const ExtractCallout = Blockquote.extend({
  renderHTML({ HTMLAttributes, node }) {
    const text = node.firstChild?.textContent ?? '';
    const isCallout = text.startsWith(MARKER);
    const cls = isCallout ? 'gb-extract-callout' : undefined;
    return ['blockquote', { ...HTMLAttributes, class: cls }, 0];
  },
});
