import { createLinkSuggestExtension } from './link-suggestion';

/** `[[` → page picker; inserts `[[<vault path>|Title]]`. */
export const WikilinkSuggest = createLinkSuggestExtension({
  name: 'wikilinkSuggest',
  kind: 'page',
  char: '[[',
  allowSpaces: true, // titles contain spaces
  allowedPrefixes: null, // Obsidian triggers `[[` anywhere
  minQueryLength: 0,
  rejectQuery: /\]/, // the user closed the link by hand
});
