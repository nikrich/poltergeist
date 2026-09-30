import { parse } from '../fountain/parse.js';

const PRINTED = new Set(['scene_heading', 'action', 'character', 'dialogue', 'parenthetical', 'transition', 'centered', 'lyric']);
const nonBlank = (s) => s.split('\n').filter((l) => l.trim()).length;

export function stripFences(s) {
  const lines = String(s ?? '').replace(/\r\n?/g, '\n').split('\n');
  const open = lines.findIndex((l) => /^[ \t]*```/.test(l));
  if (open < 0) return lines.join('\n').trim();
  const rest = lines[open].replace(/^[ \t]*```/, '');
  const body = /^[\w-]*\s*$/.test(rest) ? [] : [rest];
  for (let i = open + 1; i < lines.length; i++) {
    if (/^[ \t]*```/.test(lines[i])) break;
    body.push(lines[i]);
  }
  return body.join('\n').trim();
}

export function checkFountain(original, result, { minKeep = 0.6, keepHeading = false, requireStructure = false } = {}) {
  const text = stripFences(result);
  if (!text) return { ok: false, reason: 'empty result', text };
  const firstLine = text.split('\n')[0];
  if (/^(sure|here('s| is| are)?|certainly|of course|okay|ok|absolutely)\b.*:\s*$/i.test(firstLine)) {
    return { ok: false, reason: 'assistant chatter instead of screenplay text', text };
  }
  const els = parse(text);
  if (!els.some((e) => PRINTED.has(e.type))) return { ok: false, reason: 'no screenplay elements', text };
  const origEls = parse(original);
  const origHasStructure = origEls.some((e) => e.type === 'scene_heading' || e.type === 'character');
  if (requireStructure && origHasStructure && !els.some((e) => e.type === 'scene_heading' || e.type === 'character')) {
    return { ok: false, reason: 'lost its screenplay structure', text };
  }
  const a = nonBlank(original);
  const b = nonBlank(text);
  if (minKeep > 0 && a >= 5 && b < a * minKeep) {
    return { ok: false, reason: `lost ${Math.round(100 - (100 * b) / a)}% of its lines`, text };
  }
  if (keepHeading && origEls.some((e) => e.type === 'scene_heading') && !els.some((e) => e.type === 'scene_heading')) {
    return { ok: false, reason: 'scene heading removed', text };
  }
  return { ok: true, text };
}
