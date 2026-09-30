import { characters } from '../fountain/outline.js';

export const PREFIXES = ['INT. ', 'EXT. ', 'INT./EXT. ', 'I/E. '];
export const TIMES = ['DAY', 'NIGHT', 'CONTINUOUS', 'LATER', 'MOMENTS LATER', 'MORNING', 'EVENING'];
export const EXTENSIONS = ['(V.O.)', '(O.S.)', "(CONT'D)", '(O.C.)'];
const HEAD = /^(INT\.?\/EXT\.?|EXT\.?\/INT\.?|INT\/EXT\.?|I\/E\.?|INT\.?|EXT\.?|EST\.?)\s+/i;

export function locations(elements) {
  const counts = new Map();
  for (const el of elements) {
    if (el.type !== 'scene_heading') continue;
    const loc = el.text.replace(HEAD, '').split(' - ')[0].trim().toUpperCase();
    if (loc) counts.set(loc, (counts.get(loc) ?? 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([l]) => l);
}

function filtered(list, typed, from) {
  const u = typed.toUpperCase();
  const options = list.filter((o) => o.toUpperCase().startsWith(u) && o.toUpperCase() !== u);
  return options.length ? { from, options } : null;
}

export function completionsFor({ text, type, prevBlank, elements }) {
  if (type === 'dialogue' || type === 'parenthetical') return null;
  const head = text.match(HEAD);
  if (head && (type === 'scene_heading' || prevBlank)) {
    const rest = text.slice(head[0].length);
    const dash = rest.lastIndexOf(' - ');
    if (dash >= 0) {
      const from = head[0].length + dash + 3;
      return filtered(TIMES, text.slice(from), from);
    }
    return filtered(locations(elements), rest, head[0].length);
  }
  if (prevBlank && /^[a-z./]{1,9}$/i.test(text)) {
    const r = filtered(PREFIXES, text, 0);
    if (r) return r;
  }
  if (type === 'character' || (prevBlank && /^[A-Z][A-Z0-9 .''-]*$/.test(text))) {
    const paren = text.lastIndexOf('(');
    if (paren >= 0) return filtered(EXTENSIONS, text.slice(paren), paren);
    return filtered(characters(elements).map((ch) => ch.name), text.trim(), 0);
  }
  return null;
}
