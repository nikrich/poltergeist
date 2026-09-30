import { EditorSelection, EditorState } from '@codemirror/state';
import { describe, expect, it } from 'vitest';
import { analysisField } from '../analysis.js';
import { cycleType, enter, setType, typeAt } from '../commands.js';
import { hintField } from '../hints.js';

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
