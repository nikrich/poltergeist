export type NoteLanguage = 'af' | 'en';

// Distinctive, frequent function words only; words common to both languages
// ("is", "was", "met", "in") are left out on purpose.
const AF = new Set([
  'die', 'het', 'nie', 'van', 'en', 'ek', 'jy', 'ons', 'vir', 'ook', 'maar', 'sal', 'wat', 'hulle', 'word',
]);
const EN = new Set([
  'the', 'and', 'of', 'to', 'that', 'with', 'for', 'this', 'are', 'you', 'it', 'on', 'be', 'have', 'not',
]);

/** Dominant language of a note, for picking a read-aloud voice. Needs at
 * least three marker words and a 1.5× lead; otherwise null (use the default
 * voice). */
export function detectLanguage(text: string): NoteLanguage | null {
  const words = text.toLowerCase().match(/\p{L}+/gu) ?? [];
  let af = 0;
  let en = 0;
  for (const w of words) {
    if (AF.has(w)) af++;
    else if (EN.has(w)) en++;
  }
  if (af + en < 3) return null;
  if (af > en * 1.5) return 'af';
  if (en > af * 1.5) return 'en';
  return null;
}
