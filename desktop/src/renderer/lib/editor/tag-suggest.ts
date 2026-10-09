import { createLinkSuggestExtension } from './link-suggestion';

/** `#` → tag picker; inserts plain `#tag`. Needs one char so `# ` headings never pop it. */
export const TagSuggest = createLinkSuggestExtension({
  name: 'tagSuggest',
  kind: 'tag',
  char: '#',
  allowSpaces: false,
  allowedPrefixes: [' '],
  minQueryLength: 1,
});
