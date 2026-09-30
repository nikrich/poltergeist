import { EditorView } from '@codemirror/view';
import { typeAt } from './commands.js';
import { CAPS_TYPES } from './flow.js';

/** Scene headings, cues and transitions are always uppercase in a screenplay. */
export const autoCaps = EditorView.inputHandler.of((view, from, to, text) => {
  if (text === text.toUpperCase()) return false;
  const line = view.state.doc.lineAt(from);
  if (!CAPS_TYPES.has(typeAt(view.state, line.number))) return false;
  view.dispatch({ changes: { from, to, insert: text.toUpperCase() }, selection: { anchor: from + text.length }, userEvent: 'input.type' });
  return true;
});
