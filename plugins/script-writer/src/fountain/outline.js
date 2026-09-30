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

export function moveScene(text, from, to) {
  const heads = parse(text).filter((e) => e.type === 'scene_heading').map((e) => e.line);
  if (from === to || from < 0 || to < 0 || from >= heads.length || to >= heads.length) return text;
  const lines = text.split('\n');
  const pre = trimBlankTail(lines.slice(0, heads[0]));
  const blocks = heads.map((h, k) => trimBlankTail(lines.slice(h, heads[k + 1] ?? lines.length)));
  const [moved] = blocks.splice(from, 1);
  blocks.splice(to, 0, moved);
  const body = blocks.map((b) => b.join('\n')).join('\n\n');
  return (pre.length ? `${pre.join('\n')}\n\n` : '') + body + (text.endsWith('\n') ? '\n' : '');
}
