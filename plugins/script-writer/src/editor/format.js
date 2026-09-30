import { startCompletion } from '@codemirror/autocomplete';
import { EditorSelection } from '@codemirror/state';
import { sceneInsertPos } from '../fountain/outline.js';
import { setHint } from './hints.js';

export const MARKERS = Object.freeze({ bold: '**', italic: '*', underline: '_' });

function wrappedBy(state, from, to, m) {
  if (state.sliceDoc(from - m.length, from) !== m || state.sliceDoc(to, to + m.length) !== m) return false;
  if (m !== '*') return true;
  // a single * next to another * is part of ** - not an italic wrapper
  return state.sliceDoc(from - 2, from - 1) !== '*' && state.sliceDoc(to + 1, to + 2) !== '*';
}

export const toggleEmphasis = (kind) => ({ state, dispatch }) => {
  const m = MARKERS[kind];
  const tr = state.changeByRange((range) => {
    if (!range.empty && wrappedBy(state, range.from, range.to, m)) {
      return {
        changes: [{ from: range.from - m.length, to: range.from }, { from: range.to, to: range.to + m.length }],
        range: EditorSelection.range(range.from - m.length, range.to - m.length),
      };
    }
    return {
      changes: [{ from: range.from, insert: m }, { from: range.to, insert: m }],
      range: EditorSelection.range(range.from + m.length, range.to + m.length),
    };
  });
  dispatch(state.update(tr, { userEvent: 'input.format', scrollIntoView: true }));
  return true;
};

export function insertSceneAfterCursor(view) {
  const { state } = view;
  const line0 = state.doc.lineAt(state.selection.main.head).number - 1;
  const at = sceneInsertPos(state.doc.toString(), line0);
  const insert = '\n\nINT. ';
  view.dispatch({
    changes: { from: at, insert },
    selection: { anchor: at + insert.length },
    effects: setHint.of({ pos: at + 2, type: 'scene_heading' }),
    scrollIntoView: true,
    userEvent: 'input.scene',
  });
  view.focus();
  startCompletion(view);
  return true;
}
