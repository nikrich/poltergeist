// Fountain 1.1 parser → flat element list. `line`/`lineEnd` are 0-based
// indexes into the source split on \n. Pure — shared by the editor
// decorations, navigators, paginator and export.

export const SCENE_PREFIX = /^(?:INT\.?\/EXT|EXT\.?\/INT|INT\/EXT|I\/E|INT|EXT|EST)(?:\.|\s)/i;
const SCENE_NUMBER = /\s*#([A-Za-z0-9.-]+)#\s*$/;

const blank = (s) => s === undefined || s.trim() === '';

/** A cue has letters and none lowercase outside its (extension). */
export function isUpperCue(t) {
  const name = t.replace(/\s*\^\s*$/, '').replace(/\([^)]*\)/g, '').trim();
  return /[A-Z]/.test(name) && !/[a-z]/.test(name);
}

function sceneHeading(t, line) {
  const raw = t.startsWith('.') ? t.slice(1).trim() : t;
  const el = { type: 'scene_heading', text: raw, line, lineEnd: line };
  const m = raw.match(SCENE_NUMBER);
  if (m) {
    el.sceneNumber = m[1];
    el.text = raw.slice(0, m.index).trim();
  }
  return el;
}

function readDialogue(lines, i, out) {
  let cue = lines[i].trim();
  if (cue.startsWith('@')) cue = cue.slice(1).trim();
  const charEl = { type: 'character', text: cue, line: i, lineEnd: i };
  if (/\^\s*$/.test(cue)) {
    charEl.text = cue.replace(/\s*\^\s*$/, '');
    charEl.dual = 'right';
    for (let k = out.length - 1; k >= 0; k--) {
      const t = out[k].type;
      if (t === 'character') { out[k].dual = 'left'; break; }
      if (t !== 'dialogue' && t !== 'parenthetical') break;
    }
  }
  out.push(charEl);
  i++;
  let cur = null;
  while (i < lines.length && (!blank(lines[i]) || /^ {2,}$/.test(lines[i]))) {
    const t = lines[i].trim();
    if (/^\(.*\)$/.test(t)) {
      cur = null;
      out.push({ type: 'parenthetical', text: t, line: i, lineEnd: i });
    } else if (cur) {
      cur.text += `\n${t}`;
      cur.lineEnd = i;
    } else {
      cur = { type: 'dialogue', text: t, line: i, lineEnd: i };
      out.push(cur);
    }
    i++;
  }
  return i;
}

export function parse(text) {
  const lines = String(text ?? '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const t = lines[i].trim();
    if (t === '') { i++; continue; }
    const prevBlank = blank(lines[i - 1]);
    const nextBlank = blank(lines[i + 1]);
    const single = (type, txt, extra = {}) => {
      out.push({ type, text: txt, line: i, lineEnd: i, ...extra });
      i++;
    };

    if (t.startsWith('/*')) {
      const start = i;
      while (i < lines.length - 1 && !lines[i].includes('*/')) i++;
      out.push({ type: 'boneyard', text: lines.slice(start, i + 1).join('\n'), line: start, lineEnd: i });
      i++;
      continue;
    }
    if (/^={3,}$/.test(t)) { single('page_break', ''); continue; }
    if (t.startsWith('#')) {
      const m = t.match(/^(#+)\s*(.*)$/);
      single('section', m[2], { depth: m[1].length });
      continue;
    }
    if (t.startsWith('=')) { single('synopsis', t.slice(1).trim()); continue; }
    if (/^\[\[[\s\S]*\]\]$/.test(t)) { single('note', t.slice(2, -2).trim()); continue; }
    if (t.startsWith('~')) { single('lyric', t.slice(1).trim()); continue; }
    if (t.startsWith('>') && t.endsWith('<')) { single('centered', t.slice(1, -1).trim()); continue; }
    if (t.startsWith('>')) { single('transition', t.slice(1).trim()); continue; }
    if (prevBlank && ((t.startsWith('.') && !t.startsWith('..')) || SCENE_PREFIX.test(t))) {
      out.push(sceneHeading(t, i));
      i++;
      continue;
    }
    if (prevBlank && nextBlank && t.endsWith('TO:') && t === t.toUpperCase() && !t.startsWith('!')) { single('transition', t); continue; }
    if (prevBlank && !nextBlank && (t.startsWith('@') || (!t.startsWith('!') && isUpperCue(t)))) {
      i = readDialogue(lines, i, out);
      continue;
    }
    // Action paragraph: runs to the next blank line; each source line is a hard break.
    const start = i;
    const buf = [];
    while (i < lines.length && !blank(lines[i])) {
      const s = lines[i].trim();
      buf.push(s.startsWith('!') ? s.slice(1) : s);
      i++;
    }
    out.push({ type: 'action', text: buf.join('\n'), line: start, lineEnd: i - 1 });
  }
  return out;
}
