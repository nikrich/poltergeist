import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { Compartment, EditorState } from '@codemirror/state';
import { drawSelection, EditorView, keymap } from '@codemirror/view';
import { analysisField } from './analysis.js';
import { autoCaps } from './autocaps.js';
import { scriptCompletions } from './complete.js';
import { decorations } from './decorations.js';
import { focusMode } from './focus.js';
import { hintField } from './hints.js';
import { scriptKeymap } from './keymap.js';
import { proposalExtension, showProposal } from './proposal.js';

const focusSlot = new Compartment();

export function createEditor({ parent, doc, onDocChange, onCursorLine, onSave, onToggleFocus }) {
  const state = EditorState.create({
    doc,
    extensions: [
      analysisField,
      hintField,
      history(),
      drawSelection(),
      EditorView.lineWrapping,
      scriptKeymap({ onSave, onToggleFocus }),
      keymap.of([...historyKeymap, ...defaultKeymap]),
      decorations,
      proposalExtension,
      scriptCompletions(),
      autoCaps,
      focusSlot.of([]),
      EditorView.contentAttributes.of({ spellcheck: 'true', 'aria-label': 'Screenplay' }),
      EditorView.domEventHandlers({ blur: () => { onSave?.(); return false; } }),
      EditorView.updateListener.of((u) => {
        if (u.docChanged) onDocChange?.(u.state.doc.toString());
        if (u.docChanged || u.selectionSet) onCursorLine?.(u.state.doc.lineAt(u.state.selection.main.head).number - 1);
      }),
    ],
  });
  return new EditorView({ state, parent });
}

export function setFocusMode(view, on) {
  view.dispatch({ effects: focusSlot.reconfigure(on ? focusMode : []) });
}

export function jumpToLine(view, line0) {
  const n = Math.min(Math.max(line0 + 1, 1), view.state.doc.lines);
  const pos = view.state.doc.line(n).from;
  view.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: 'start', yMargin: 96 }) });
  view.focus();
}

export function proposeEdit(view, proposal) {
  view.dispatch({ effects: [showProposal.of(proposal), EditorView.scrollIntoView(proposal.to, { y: 'center' })] });
}
