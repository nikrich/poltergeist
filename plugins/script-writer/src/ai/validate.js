import { parse } from '../fountain/parse.js';

const PRINTED = new Set(['scene_heading', 'action', 'character', 'dialogue', 'parenthetical', 'transition', 'centered', 'lyric']);
const nonBlank = (s) => s.split('\n').filter((l) => l.trim()).length;

export function stripFences(s) {
  return String(s ?? '').replace(/\r\n?/g, '\n').replace(/^\s*```[a-z]*\n?/i, '').replace(/\n?```\s*$/, '').trim();
}

export function checkFountain(original, result, { minKeep = 0.6, keepHeading = false } = {}) {
  const text = stripFences(result);
  if (!text) return { ok: false, reason: 'empty result', text };
  const els = parse(text);
  if (!els.some((e) => PRINTED.has(e.type))) return { ok: false, reason: 'no screenplay elements', text };
  const a = nonBlank(original);
  const b = nonBlank(text);
  if (minKeep > 0 && a >= 5 && b < a * minKeep) {
    return { ok: false, reason: `lost ${Math.round(100 - (100 * b) / a)}% of its lines`, text };
  }
  if (keepHeading && parse(original).some((e) => e.type === 'scene_heading') && !els.some((e) => e.type === 'scene_heading')) {
    return { ok: false, reason: 'scene heading removed', text };
  }
  return { ok: true, text };
}
