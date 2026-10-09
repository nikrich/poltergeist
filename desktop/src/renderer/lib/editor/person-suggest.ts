import { createLinkSuggestExtension } from './link-suggestion';

/** `@` → people picker; inserts `[[30-cross-context/people/<slug>|@Name]]`. */
export const PersonSuggest = createLinkSuggestExtension({
  name: 'personSuggest',
  kind: 'person',
  char: '@',
  allowSpaces: false,
  allowedPrefixes: [' '], // never inside an email address
  minQueryLength: 0,
});
