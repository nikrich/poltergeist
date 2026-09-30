// An AI suggestion shown inline: the target range struck through and the
// proposed Fountain in a block widget with Accept / Insert / Reject.
// Editing inside (or at the edges of) the target cancels the proposal.
import { StateEffect, StateField } from '@codemirror/state';
import { Decoration, EditorView, keymap, WidgetType } from '@codemirror/view';

export const showProposal = StateEffect.define();
export const clearProposal = StateEffect.define();

export const proposalField = StateField.define({
  create: () => null,
  update(p, tr) {
    for (const e of tr.effects) {
      if (e.is(clearProposal)) return null;
      if (e.is(showProposal)) return { ...e.value };
    }
    if (!p || !tr.docChanged) return p;
    let touched = false;
    tr.changes.iterChangedRanges((fromA, toA) => { if (fromA <= p.to && toA >= p.from) touched = true; });
    if (touched) return null;
    return { ...p, from: tr.changes.mapPos(p.from, 1), to: tr.changes.mapPos(p.to, -1) };
  },
  provide: (f) => EditorView.decorations.from(f, (p) => (p ? buildDecorations(p) : Decoration.none)),
});

export function acceptProposal(view) {
  const p = view.state.field(proposalField, false);
  if (!p) return false;
  if (p.mode === 'insert') return insertProposal(view);
  view.dispatch({
    changes: { from: p.from, to: p.to, insert: p.text },
    selection: { anchor: p.from + p.text.length },
    effects: clearProposal.of(null),
    userEvent: 'input.ai',
  });
  return true;
}

export function insertProposal(view) {
  const p = view.state.field(proposalField, false);
  if (!p) return false;
  const insert = `\n\n${p.text}`;
  view.dispatch({
    changes: { from: p.to, insert },
    selection: { anchor: p.to + insert.length },
    effects: clearProposal.of(null),
    userEvent: 'input.ai',
  });
  return true;
}

export function rejectProposal(view) {
  if (!view.state.field(proposalField, false)) return false;
  view.dispatch({ effects: clearProposal.of(null) });
  return true;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

class ProposalWidget extends WidgetType {
  constructor(p) { super(); this.p = p; }

  eq(other) { return other.p.text === this.p.text && other.p.mode === this.p.mode && other.p.label === this.p.label; }

  toDOM(view) {
    const wrap = el('div', 'sw-proposal');
    wrap.append(el('div', 'sw-proposal-head', `AI \u00b7 ${this.p.label ?? 'suggestion'}`), el('pre', 'sw-proposal-text', this.p.text));
    const bar = el('div', 'sw-proposal-bar');
    const button = (label, fn, cls = '') => {
      const b = el('button', `sw-btn ${cls}`.trim(), label);
      b.type = 'button';
      b.addEventListener('mousedown', (e) => { e.preventDefault(); fn(view); });
      bar.append(b);
    };
    if (this.p.mode === 'replace') button('Accept', acceptProposal, 'sw-primary');
    button(this.p.mode === 'replace' ? 'Insert below' : 'Insert', insertProposal, this.p.mode === 'insert' ? 'sw-primary' : '');
    button('Reject', rejectProposal);
    wrap.append(bar);
    return wrap;
  }

  ignoreEvent() { return true; }
}

function buildDecorations(p) {
  const ranges = [];
  if (p.mode === 'replace' && p.to > p.from) ranges.push(Decoration.mark({ class: 'sw-del' }).range(p.from, p.to));
  ranges.push(Decoration.widget({ widget: new ProposalWidget(p), block: true, side: 1 }).range(p.to));
  return Decoration.set(ranges, true);
}

export const proposalExtension = [
  proposalField,
  keymap.of([{ key: 'Escape', run: rejectProposal }]),
];

// True when the script changed under an in-flight AI proposal.
export function isStaleProposal(state, p) {
  return p.to > state.doc.length || state.sliceDoc(p.anchorFrom ?? p.from, p.to) !== p.original;
}
