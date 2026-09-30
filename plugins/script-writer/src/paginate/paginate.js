// Elements → positioned page lines using standard screenplay geometry
// (Courier 12pt: 10 cpi, 6 lpi; 1.5"/1" margins → 60 cols × 54 rows).
import { visibleLength, wrap } from './wrap.js';

export const LINES_PER_PAGE = 54;
export const LAYOUT = {
  scene_heading: { x: 0, width: 60, upper: true },
  action: { x: 0, width: 60 },
  character: { x: 22, width: 38, upper: true },
  parenthetical: { x: 16, width: 25 },
  dialogue: { x: 10, width: 35 },
  transition: { x: 0, width: 60, upper: true, align: 'right' },
  centered: { x: 0, width: 60, align: 'center' },
  lyric: { x: 0, width: 60, italic: true },
};
const DUAL = {
  character: { x: 8, width: 20, upper: true },
  parenthetical: { x: 4, width: 22 },
  dialogue: { x: 0, width: 28 },
};
const DUAL_RIGHT = 31;
const SENTENCE_END = /[.!?…]["'"')]*$/;

const clean = (s) => s.replace(/\[\[[\s\S]*?\]\]/g, '').replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/ {2,}/g, ' ').replace(/[ \t]+$/gm, '');

function layout(type, text, spec, el, base = 0) {
  const t = spec.upper ? clean(text).toUpperCase() : clean(text);
  return wrap(t, spec.width).map((w) => {
    let x = base + spec.x;
    if (spec.align === 'right') x = base + spec.width - visibleLength(w);
    if (spec.align === 'center') x = base + Math.floor((spec.width - visibleLength(w)) / 2);
    return spec.italic ? { type, text: w, x, el, italic: true } : { type, text: w, x, el };
  });
}

function toBlocks(elements, sceneNumbers) {
  const blocks = [];
  let scene = 0;
  for (let k = 0; k < elements.length; k++) {
    const el = elements[k];
    if (el.type === 'page_break') { blocks.push({ kind: 'break' }); continue; }
    if (el.type === 'character') {
      const parts = [{ el, idx: k }];
      while (k + 1 < elements.length && (elements[k + 1].type === 'dialogue' || elements[k + 1].type === 'parenthetical')) {
        k++;
        parts.push({ el: elements[k], idx: k });
      }
      const lay = (L, base) => parts.flatMap((p) => layout(p.el.type, p.el.text, L[p.el.type], p.idx, base));
      const block = { kind: 'dialogue', dual: el.dual, cue: clean(el.text).toUpperCase(), lines: lay(LAYOUT, 0), narrow: (b) => lay(DUAL, b) };
      const prev = blocks[blocks.length - 1];
      if (el.dual === 'right' && prev?.kind === 'dialogue' && prev.dual === 'left') {
        blocks[blocks.length - 1] = { kind: 'dual', left: prev.narrow(0), right: block.narrow(DUAL_RIGHT) };
      } else {
        blocks.push(block);
      }
      continue;
    }
    const spec = LAYOUT[el.type];
    if (!spec) continue; // sections, synopses, notes, boneyard don't print
    const lines = layout(el.type, el.text, spec, k);
    if (el.type === 'scene_heading') {
      scene++;
      const num = el.sceneNumber ?? (sceneNumbers ? String(scene) : undefined);
      if (num && lines[0]) lines[0].sceneNumber = num;
    }
    blocks.push({ kind: el.type, lines });
  }
  return blocks;
}

const height = (b) => (b.kind === 'dual' ? Math.max(b.left.length, b.right.length) : b.lines.length);

export function paginate(elements, { sceneNumbers = false, linesPerPage = LINES_PER_PAGE } = {}) {
  const blocks = toBlocks(elements, sceneNumbers);
  const pages = [];
  let page;
  let y;
  const newPage = () => { page = { number: pages.length + 1, lines: [] }; pages.push(page); y = 0; };
  const top = () => (y === 0 ? 0 : y + 1);
  const fits = (n) => top() + n <= linesPerPage;
  const put = (lines, at) => {
    lines.forEach((l, n) => page.lines.push({ ...l, y: at + n }));
    y = at + lines.length;
  };
  const putForced = (lines) => {
    let rest = lines;
    while (rest.length) {
      let at = top();
      if (at >= linesPerPage) { newPage(); at = 0; }
      const room = linesPerPage - at;
      put(rest.slice(0, room), at);
      rest = rest.slice(room);
      if (rest.length) newPage();
    }
  };
  // Move a block that can't split to the next page — unless the page ends in
  // the scene heading that owns it; then force-split rather than orphan it.
  const moveWhole = (lines) => {
    const afterHeading = page.lines.length > 0 && page.lines[page.lines.length - 1].type === 'scene_heading';
    if (y > 0 && !afterHeading) newPage();
    putForced(lines);
  };
  const splitAction = (lines) => {
    const at = top();
    for (let k = Math.min(linesPerPage - at, lines.length - 2); k >= 2; k--) {
      if (!SENTENCE_END.test(lines[k - 1].text)) continue;
      put(lines.slice(0, k), at);
      newPage();
      putForced(lines.slice(k));
      return true;
    }
    return false;
  };
  const splitDialogue = ({ lines, cue }) => {
    const at = top();
    const valid = (k) => lines.length - k >= 2
      && lines[k - 1].type !== 'parenthetical' && lines[k - 1].type !== 'character' && lines[k].type !== 'character';
    let best = -1;
    for (let k = Math.min(linesPerPage - at - 1, lines.length - 2); k >= 3; k--) {
      if (!valid(k)) continue;
      if (best < 0) best = k;
      if (lines[k - 1].type === 'dialogue' && SENTENCE_END.test(lines[k - 1].text)) { best = k; break; }
    }
    if (best < 0) return false;
    put([...lines.slice(0, best), { type: 'more', text: '(MORE)', x: LAYOUT.character.x, el: -1 }], at);
    newPage();
    const contd = /\(CONT['']D\)/i.test(cue) ? cue : `${cue} (CONT'D)`;
    putForced([{ type: 'character', text: contd, x: LAYOUT.character.x, el: -1 }, ...lines.slice(best)]);
    return true;
  };

  newPage();
  for (let b = 0; b < blocks.length; b++) {
    const block = blocks[b];
    if (block.kind === 'break') { if (y > 0) newPage(); continue; }
    if (block.kind === 'dual') {
      const h = height(block);
      if (!fits(h) && y > 0) newPage();
      const at = top();
      block.left.forEach((l, n) => page.lines.push({ ...l, y: at + n }));
      block.right.forEach((l, n) => page.lines.push({ ...l, y: at + n }));
      y = at + h;
      continue;
    }
    const { lines } = block;
    if (block.kind === 'scene_heading') {
      const next = blocks[b + 1];
      const keep = next && next.kind !== 'break' ? 1 + Math.min(2, height(next)) : 0;
      if (!fits(lines.length + keep) && y > 0) newPage();
      put(lines, top());
      continue;
    }
    if (fits(lines.length)) { put(lines, top()); continue; }
    if (block.kind === 'action' && splitAction(lines)) continue;
    if (block.kind === 'dialogue' && splitDialogue(block)) continue;
    moveWhole(lines);
  }
  if (pages.length > 1 && pages[pages.length - 1].lines.length === 0) pages.pop();
  return pages;
}
