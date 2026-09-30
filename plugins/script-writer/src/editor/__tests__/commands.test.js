import { history, undo } from '@codemirror/commands';
import { EditorSelection, EditorState } from '@codemirror/state';
import { describe, expect, it } from 'vitest';
import { analysisField } from '../analysis.js';
import { cycleType, enter, setType, typeAt } from '../commands.js';
import { hintAt, hintField } from '../hints.js';

const mk = (doc, cursor = doc.length) => EditorState.create({
  doc, selection: EditorSelection.cursor(cursor), extensions: [analysisField, hintField],
});
const run = (cmd, state) => {
  let next = state;
  const handled = cmd({ state, dispatch: (tr) => { next = tr.state; } });
  return { state: next, handled };
};
const doc = (s) => s.doc.toString();
const head = (s) => s.selection.main.head;

describe('Tab cycling', () => {
  it('turns a lowercase action line into an uppercase character', () => {
    const { state } = run(cycleType(1), mk('Go.\n\nmara'));
    expect(doc(state)).toBe('Go.\n\nMARA');
    expect(typeAt(state, 3)).toBe('character');
  });

  it('walks action → character → transition → scene heading → action outside dialogue', () => {
    let s = mk('night falls');
    const seen = [];
    for (let k = 0; k < 4; k++) { s = run(cycleType(1), s).state; seen.push([typeAt(s, 1), doc(s)]); }
    expect(seen).toEqual([
      ['character', 'NIGHT FALLS'],
      ['transition', '>NIGHT FALLS'],
      ['scene_heading', '.NIGHT FALLS'],
      ['action', '!NIGHT FALLS'],
    ]);
  });

  it('inserts () with the cursor inside on an empty line under a cue', () => {
    const start = run(enter, mk('MARA')).state; // → "MARA\n", dialogue hint
    const { state } = run(cycleType(1), start);
    expect(doc(state)).toBe('MARA\n()');
    expect(head(state)).toBe(6);
    expect(typeAt(state, 2)).toBe('parenthetical');
  });

  it('Mod-number sets a type directly', () => {
    const { state } = run(setType('transition'), mk('cut to:'));
    expect(doc(state)).toBe('CUT TO:');
  });
});

describe('Enter flow', () => {
  it('scene heading → blank line + action, uppercasing the heading', () => {
    const { state } = run(enter, mk('int. house - day'));
    expect(doc(state)).toBe('INT. HOUSE - DAY\n\n');
    expect(head(state)).toBe(18);
    expect(typeAt(state, 3)).toBe('action');
  });

  it('a cue-looking line → dialogue directly below, cue hinted as character', () => {
    const { state } = run(enter, mk('Go.\n\nMARA'));
    expect(doc(state)).toBe('Go.\n\nMARA\n');
    expect(typeAt(state, 3)).toBe('character');
    expect(typeAt(state, 4)).toBe('dialogue');
  });

  it('dialogue → blank line + character', () => {
    const { state } = run(enter, mk('MARA\nHello.'));
    expect(doc(state)).toBe('MARA\nHello.\n\n');
    expect(typeAt(state, 4)).toBe('character');
  });

  it('Enter on an empty hinted line resets it to action without inserting', () => {
    const afterDialogue = run(enter, mk('MARA\nHello.')).state;
    const { state, handled } = run(enter, afterDialogue);
    expect(handled).toBe(true);
    expect(doc(state)).toBe('MARA\nHello.\n\n');
    expect(typeAt(state, 4)).toBe('action');
  });

  it('Enter inside the closing paren of a parenthetical continues to dialogue', () => {
    const s = mk('MARA\n(quietly)', 'MARA\n(quietly'.length);
    const { state } = run(enter, s);
    expect(doc(state)).toBe('MARA\n(quietly)\n');
    expect(typeAt(state, 3)).toBe('dialogue');
  });

  it('falls through (returns false) mid-line and on plain empty lines', () => {
    expect(run(enter, mk('Hello there', 3)).handled).toBe(false);
    expect(run(enter, mk('Go.\n\n')).handled).toBe(false);
  });
});

describe('hint lifecycle', () => {
  it('deleting the newline after Enter on a cue leaves no stale dialogue hint', () => {
    const s = run(enter, mk('MARA')).state;
    const st = s.update({ changes: { from: 4, to: 5 } }).state;
    expect(doc(st)).toBe('MARA');
    expect(typeAt(st, 1)).not.toBe('dialogue');
    expect(st.field(hintField)).toHaveLength(1);
  });

  it('a whole-doc replace leaves no hints', () => {
    const s = run(enter, mk('MARA')).state;
    const st = s.update({ changes: { from: 0, to: s.doc.length, insert: 'x' } }).state;
    expect(st.field(hintField)).toEqual([]);
  });

  it('typing at the start of a hinted empty dialogue line keeps the hint', () => {
    const s = run(enter, mk('MARA')).state;
    const st = s.update({ changes: { from: 5, insert: 'H' }, selection: EditorSelection.cursor(6) }).state;
    expect(typeAt(st, 2)).toBe('dialogue');
  });

  it('undoing an Enter after a cue never leaves a dialogue hint', () => {
    const base = EditorState.create({
      doc: 'MARA', selection: EditorSelection.cursor(4), extensions: [analysisField, hintField, history()],
    });
    const after = run(enter, base).state;
    const { state } = run(undo, after);
    expect(doc(state)).toBe('MARA');
    expect(['character', 'action']).toContain(typeAt(state, 1));
  });

  it('hintAt is null outside the document', () => {
    const s = mk('a');
    expect(hintAt(s, 0)).toBeNull();
    expect(hintAt(s, 5)).toBeNull();
  });
});

describe('Enter with content below', () => {
  it('action line with a paragraph below gets its own blank-separated paragraph', () => {
    const { state } = run(enter, mk('Line one\nnext para', 8));
    expect(doc(state)).toBe('Line one\n\n\n\nnext para');
    expect(state.doc.lineAt(head(state)).number).toBe(3);
  });

  it('a cue with dialogue below just moves into the dialogue', () => {
    const { state, handled } = run(enter, mk('MARA\nHello.', 4));
    expect(handled).toBe(true);
    expect(doc(state)).toBe('MARA\nHello.');
    expect(head(state)).toBe(5);
  });

  it('dialogue with more text below opens a new cue paragraph', () => {
    const { state } = run(enter, mk('MARA\nHi.\nMore.', 8));
    expect(doc(state)).toBe('MARA\nHi.\n\n\n\nMore.');
    expect(state.doc.lineAt(head(state)).number).toBe(4);
    expect(typeAt(state, 4)).toBe('character');
  });
});
