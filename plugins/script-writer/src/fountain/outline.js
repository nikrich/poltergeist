import { parse } from './parse.js';

export function scenes(elements) {
  const out = [];
  for (const el of elements) {
    if (el.type === 'scene_heading') {
      out.push({ heading: el.text.toUpperCase(), line: el.line, sceneNumber: el.sceneNumber, synopsis: '' });
    } else if (el.type === 'synopsis' && out.length && !out[out.length - 1].synopsis) {
      out[out.length - 1].synopsis = el.text;
    }
  }
  return out.map(({ sceneNumber, ...s }, index) => ({ index, number: sceneNumber ?? String(index + 1), ...s }));
}

export const cueName = (text) => text.replace(/^@/, '').replace(/\s*\^\s*$/, '').replace(/\([^)]*\)/g, '').trim().toUpperCase();

export function characters(elements) {
  const map = new Map();
  for (const el of elements) {
    if (el.type !== 'character') continue;
    const name = cueName(el.text);
    if (!name) continue;
    const entry = map.get(name) ?? { name, count: 0, lines: [] };
    entry.count++;
    entry.lines.push(el.line);
    map.set(name, entry);
  }
  return [...map.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

const trimBlankTail = (arr) => {
  const a = [...arr];
  while (a.length && a[a.length - 1].trim() === '') a.pop();
  return a;
};

export function sceneBlocks(text) {
  const heads = parse(text).filter((e) => e.type === 'scene_heading').map((e) => e.line);
  const lines = text.split('\n');
  const first = heads.length ? heads[0] : lines.length;
  return {
    pre: trimBlankTail(lines.slice(0, first)).join('\n'),
    blocks: heads.map((h, k) => ({ line: h, text: trimBlankTail(lines.slice(h, heads[k + 1] ?? lines.length)).join('\n') })),
    trailingNewline: text.endsWith('\n'),
  };
}

export function joinBlocks({ pre, blocks, trailingNewline }) {
  const parts = [pre, ...blocks.map((b) => b.text)].filter((p) => p.trim() !== '');
  return parts.join('\n\n') + (trailingNewline ? '\n' : '');
}

export function moveScene(text, from, to) {
  const sb = sceneBlocks(text);
  const n = sb.blocks.length;
  if (from === to || from < 0 || to < 0 || from >= n || to >= n) return text;
  const blocks = [...sb.blocks];
  const [moved] = blocks.splice(from, 1);
  blocks.splice(to, 0, moved);
  return joinBlocks({ ...sb, blocks });
}

export function sceneRange(text, line0) {
  const lines = text.split('\n');
  const heads = parse(text).filter((e) => e.type === 'scene_heading').map((e) => e.line);
  let start = 0;
  for (const h of heads) if (h <= line0) start = h;
  const next = heads.find((h) => h > line0);
  let end = (next ?? lines.length) - 1;
  while (end > start && lines[end].trim() === '') end--;
  return { startLine: start, endLine: Math.max(start, end) };
}

export function sceneInsertPos(text, line0) {
  const { endLine } = sceneRange(text, line0);
  return text.split('\n').slice(0, endLine + 1).join('\n').length;
}
