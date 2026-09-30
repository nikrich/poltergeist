import { RangeSetBuilder } from '@codemirror/state';
import { Decoration, ViewPlugin } from '@codemirror/view';
import { typeAt } from './commands.js';
import { markerRanges } from './flow.js';

const lineDeco = new Map();
const lineClass = (type) => {
  if (!lineDeco.has(type)) lineDeco.set(type, Decoration.line({ class: `sw-l-${type}` }));
  return lineDeco.get(type);
};
const markDeco = { 'sw-marker': Decoration.mark({ class: 'sw-marker' }), 'sw-note': Decoration.mark({ class: 'sw-note' }) };

function build(view) {
  const b = new RangeSetBuilder();
  const { state } = view;
  for (const { from, to } of view.visibleRanges) {
    for (let pos = from; pos <= to;) {
      const line = state.doc.lineAt(pos);
      const type = typeAt(state, line.number);
      if (type) {
        b.add(line.from, line.from, lineClass(type));
        for (const [s, e, cls] of markerRanges(line.text, type)) if (e > s) b.add(line.from + s, line.from + e, markDeco[cls]);
      }
      pos = line.to + 1;
    }
  }
  return b.finish();
}

export const decorations = ViewPlugin.fromClass(class {
  constructor(view) { this.decorations = build(view); }
  update(u) {
    if (u.docChanged || u.viewportChanged || u.selectionSet || u.transactions.some((t) => t.effects.length)) {
      this.decorations = build(u.view);
    }
  }
}, { decorations: (v) => v.decorations });
