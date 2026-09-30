import { EditorSelection } from '@codemirror/state';
import { analysisField } from './analysis.js';
import { CAPS_TYPES, NEXT_ON_ENTER, applyType, looksLikeCue, nextInCycle } from './flow.js';
import { hintAt, setHint } from './hints.js';

export function typeAt(state, lineNo) {
  if (lineNo < 1 || lineNo > state.doc.lines) return null;
  return hintAt(state, lineNo) ?? state.field(analysisField).lineTypes[lineNo - 1] ?? null;
}

const isBlankLine = (state, n) => n < 1 || n > state.doc.lines || state.doc.line(n).text.trim() === '';

function retype(state, line, type) {
  const empty = line.text.trim() === '';
  const insert = empty ? (type === 'parenthetical' ? '()' : '') : applyType(line.text, type);
  const cursor = line.from + (type === 'parenthetical' ? insert.length - 1 : insert.length);
  return state.update({
    changes: { from: line.from, to: line.to, insert },
    selection: EditorSelection.cursor(cursor),
    effects: setHint.of({ pos: line.from, type }),
    userEvent: 'input.type',
  });
}

export const cycleType = (dir) => ({ state, dispatch }) => {
  const line = state.doc.lineAt(state.selection.main.head);
  const cur = typeAt(state, line.number);
  const prev = isBlankLine(state, line.number - 1) ? null : typeAt(state, line.number - 1);
  const allowParen = ['character', 'dialogue', 'parenthetical'].includes(prev) || cur === 'dialogue';
  dispatch(retype(state, line, nextInCycle(cur, dir, allowParen)));
  return true;
};

export const setType = (type) => ({ state, dispatch }) => {
  dispatch(retype(state, state.doc.lineAt(state.selection.main.head), type));
  return true;
};

export function enter({ state, dispatch }) {
  const sel = state.selection.main;
  if (!sel.empty) return false;
  const line = state.doc.lineAt(sel.head);
  const after = line.text.slice(sel.head - line.from);
  if (after !== '' && after.trim() !== ')') return false; // mid-line: default newline
  if (line.text.trim() === '') {
    const h = hintAt(state, line.number);
    if (!h || h === 'action') return false;
    dispatch(state.update({ effects: setHint.of({ pos: line.from, type: 'action' }) }));
    return true;
  }
  let type = typeAt(state, line.number) ?? 'action';
  if (type === 'action' && isBlankLine(state, line.number - 1) && looksLikeCue(line.text)) type = 'character';
  const rule = NEXT_ON_ENTER[type] ?? NEXT_ON_ENTER.action;
  const text = CAPS_TYPES.has(type) ? line.text.toUpperCase() : line.text;
  const pos = line.from + text.length + rule.insert.length;
  const effects = [setHint.of({ pos, type: rule.next })];
  if (type === 'character') effects.push(setHint.of({ pos: line.from, type: 'character' }));
  dispatch(state.update({
    changes: { from: line.from, to: line.to, insert: text + rule.insert },
    selection: EditorSelection.cursor(pos),
    effects,
    scrollIntoView: true,
    userEvent: 'input',
  }));
  return true;
}
