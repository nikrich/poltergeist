import { EditorState, RangeSetBuilder } from '@codemirror/state';
import { Decoration, EditorView, ViewPlugin } from '@codemirror/view';

const dim = Decoration.line({ class: 'sw-dim' });

function paragraph(doc, n) {
  let a = n;
  let b = n;
  while (a > 1 && doc.line(a - 1).text.trim() !== '') a--;
  while (b < doc.lines && doc.line(b + 1).text.trim() !== '') b++;
  return [a, b];
}

function build(view) {
  const { doc } = view.state;
  const [a, b] = paragraph(doc, doc.lineAt(view.state.selection.main.head).number);
  const out = new RangeSetBuilder();
  for (const { from, to } of view.visibleRanges) {
    for (let pos = from; pos <= to;) {
      const line = doc.lineAt(pos);
      if (line.number < a || line.number > b) out.add(line.from, line.from, dim);
      pos = line.to + 1;
    }
  }
  return out.finish();
}

const dimmer = ViewPlugin.fromClass(class {
  constructor(v) { this.decorations = build(v); }
  update(u) { if (u.docChanged || u.selectionSet || u.viewportChanged) this.decorations = build(u.view); }
}, { decorations: (v) => v.decorations });

/** Typewriter scrolling: keep the caret vertically centred. */
const typewriter = EditorState.transactionExtender.of((tr) => (
  tr.selection || tr.docChanged ? { effects: EditorView.scrollIntoView(tr.newSelection.main.head, { y: 'center' }) } : null
));

export const focusMode = [dimmer, typewriter];
