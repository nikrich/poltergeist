import { sceneRange } from '../fountain/outline.js';
import { analysisField } from './analysis.js';

/** What the AI needs from the editor: full text, parse, current scene, selection. */
export function editorContext(state) {
  const text = state.doc.toString();
  const sel = state.selection.main;
  const cursorLine = state.doc.lineAt(sel.head).number - 1;
  const { startLine, endLine } = sceneRange(text, cursorLine);
  const from = state.doc.line(startLine + 1).from;
  const to = state.doc.line(endLine + 1).to;
  return {
    text,
    elements: state.field(analysisField).elements,
    cursorLine,
    scene: { from, to, text: state.sliceDoc(from, to) },
    selection: { from: sel.from, to: sel.to, text: state.sliceDoc(sel.from, sel.to) },
  };
}
