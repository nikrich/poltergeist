// @vitest-environment jsdom
import { EditorSelection, EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { describe, expect, it } from 'vitest';
import { analysisField } from '../analysis.js';
import { insertSceneAfterCursor, toggleEmphasis } from '../format.js';
import { hintField } from '../hints.js';

const run = (cmd, state) => { let s = state; cmd({ state, dispatch: (tr) => { s = tr.state; } }); return s; };
const st = (doc, sel) => EditorState.create({ doc, selection: sel, extensions: [analysisField, hintField] });

describe('toggleEmphasis', () => {
  it('wraps the selection and keeps it selected', () => {
    const s = run(toggleEmphasis('bold'), st('She runs fast.', EditorSelection.range(4, 8)));
    expect(s.doc.toString()).toBe('She **runs** fast.');
    expect(s.sliceDoc(s.selection.main.from, s.selection.main.to)).toBe('runs');
  });
  it('unwraps when the selection is already wrapped', () => {
    const s = run(toggleEmphasis('underline'), st('She _runs_ fast.', EditorSelection.range(5, 9)));
    expect(s.doc.toString()).toBe('She runs fast.');
  });
  it('does not treat bold as italic', () => {
    const s = run(toggleEmphasis('italic'), st('She **runs** fast.', EditorSelection.range(6, 10)));
    expect(s.doc.toString()).toBe('She ***runs*** fast.');
  });
  it('inserts a marker pair at an empty cursor', () => {
    const s = run(toggleEmphasis('italic'), st('Go', EditorSelection.cursor(2)));
    expect(s.doc.toString()).toBe('Go**');
    expect(s.selection.main.head).toBe(3);
  });
});

describe('insertSceneAfterCursor', () => {
  it('adds INT. after the current scene, before the next one', () => {
    const doc = 'INT. A - DAY\n\nHi.\n\nINT. B - DAY\n\nYo.';
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    const view = new EditorView({ state: st(doc, EditorSelection.cursor(15)), parent });
    expect(insertSceneAfterCursor(view)).toBe(true);
    expect(view.state.doc.toString()).toBe('INT. A - DAY\n\nHi.\n\nINT. \n\nINT. B - DAY\n\nYo.');
    expect(view.state.selection.main.head).toBe('INT. A - DAY\n\nHi.\n\nINT. '.length);
    view.destroy();
  });
});
