// Pure element-flow rules (Final Draft conventions over Fountain text).
import { isUpperCue, SCENE_PREFIX } from '../fountain/parse.js';

export const CYCLE = ['action', 'character', 'parenthetical', 'transition', 'scene_heading'];
export const CAPS_TYPES = new Set(['character', 'scene_heading', 'transition']);
export const NEXT_ON_ENTER = {
  scene_heading: { insert: '\n\n', next: 'action' },
  action: { insert: '\n\n', next: 'action' },
  character: { insert: '\n', next: 'dialogue' },
  parenthetical: { insert: '\n', next: 'dialogue' },
  dialogue: { insert: '\n\n', next: 'character' },
  transition: { insert: '\n\n', next: 'scene_heading' },
  centered: { insert: '\n\n', next: 'action' },
  lyric: { insert: '\n\n', next: 'action' },
};

export function stripMarkers(text) {
  let s = text.trim();
  if (s.startsWith('@') || s.startsWith('!') || s.startsWith('~')) s = s.slice(1);
  else if (s.startsWith('>')) s = s.slice(1).replace(/<\s*$/, '');
  else if (s.startsWith('.') && !s.startsWith('..')) s = s.slice(1);
  if (/^\(.*\)$/.test(s)) s = s.slice(1, -1);
  return s.trim();
}

export function applyType(text, type) {
  const s = stripMarkers(text);
  const u = s.toUpperCase();
  switch (type) {
    case 'character': return u;
    case 'parenthetical': return `(${s})`;
    case 'transition': return u.endsWith('TO:') ? u : `>${u}`;
    case 'scene_heading': return SCENE_PREFIX.test(u) ? u : `.${u}`;
    case 'centered': return `>${s}<`;
    case 'lyric': return `~${s}`;
    case 'action': return isUpperCue(s) || SCENE_PREFIX.test(s) ? `!${s}` : s;
    default: return s; // dialogue
  }
}

export function looksLikeCue(text) {
  const t = text.trim();
  return t.length > 0 && t.length <= 38 && isUpperCue(t) && !SCENE_PREFIX.test(t) && !t.endsWith('TO:');
}

export function nextInCycle(current, dir, allowParen) {
  if (current === 'dialogue' && allowParen) return dir > 0 ? 'parenthetical' : 'character';
  const order = CYCLE.filter((t) => t !== 'parenthetical' || allowParen);
  const idx = Math.max(0, order.indexOf(current ?? 'action'));
  return order[(idx + dir + order.length) % order.length];
}

const LEAD = { scene_heading: '.', character: '@', action: '!', transition: '>', centered: '>', lyric: '~', synopsis: '=', section: '#' };

export function markerRanges(text, type) {
  const r = [];
  const lead = text.length - text.trimStart().length;
  const t = text.trimStart();
  if (LEAD[type] && t[0] === LEAD[type] && !(type === 'scene_heading' && t[1] === '.')) r.push([lead, lead + 1, 'sw-marker']);
  if (type === 'centered' && text.trimEnd().endsWith('<')) {
    const e = text.trimEnd().length;
    r.push([e - 1, e, 'sw-marker']);
  }
  if (type === 'scene_heading') {
    const m = text.match(/#[A-Za-z0-9.-]+#\s*$/);
    if (m) r.push([m.index, m.index + m[0].trimEnd().length, 'sw-marker']);
  }
  if (type === 'character') {
    const m = text.match(/\^\s*$/);
    if (m) r.push([m.index, m.index + 1, 'sw-marker']);
  }
  for (const m of text.matchAll(/\[\[[\s\S]*?\]\]/g)) r.push([m.index, m.index + m[0].length, 'sw-note']);
  return r.sort((a, b) => a[0] - b[0]);
}
