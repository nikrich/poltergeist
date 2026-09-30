// Typed-element hints for lines Fountain can't classify yet (an empty line
// after a cue is "dialogue" before any text exists). Hints live only on the
// cursor line and the line above it; everywhere else the parse is the truth.
import { StateEffect, StateField } from '@codemirror/state';

export const setHint = StateEffect.define();

export const hintField = StateField.define({
  create: () => [],
  update(hints, tr) {
    const doc = tr.newDoc;
    let next = hints.map((h) => ({ ...h, pos: tr.changes.mapPos(h.pos, -1) }));
    for (const e of tr.effects) {
      if (!e.is(setHint)) continue;
      const line = doc.lineAt(e.value.pos);
      next = next.filter((h) => doc.lineAt(h.pos).number !== line.number).concat({ pos: line.from, type: e.value.type });
    }
    const cur = doc.lineAt(tr.newSelection.main.head).number;
    return next.filter((h) => {
      const n = doc.lineAt(h.pos).number;
      return n === cur || n === cur - 1;
    });
  },
});

export function hintAt(state, lineNo) {
  const line = state.doc.line(lineNo);
  const h = (state.field(hintField, false) ?? []).find((x) => x.pos >= line.from && x.pos <= line.to);
  return h?.type ?? null;
}
