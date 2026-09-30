// @vitest-environment jsdom
import { EditorSelection, EditorState } from '@codemirror/state';
import { EditorView } from '@codemirror/view';
import { describe, expect, it } from 'vitest';
import { analysisField } from '../analysis.js';
import { editorContext } from '../context.js';
import { acceptProposal, isStaleProposal, insertProposal, proposalExtension, proposalField, rejectProposal, showProposal } from '../proposal.js';

const DOC = 'INT. A - DAY\n\nMara waits.\n\nINT. B - DAY\n\nGo.';
const mk = (doc = DOC, sel = EditorSelection.cursor(16)) => EditorState.create({ doc, selection: sel, extensions: [analysisField, proposalExtension] });
const viewOf = (state) => {
  const v = { state, dispatch: (spec) => { v.state = v.state.update(spec).state; } };
  return v;
};
const P = { from: 14, to: 25, text: 'Mara paces.', mode: 'replace', label: 'Rewrite' };

describe('proposal field', () => {
  it('shows, maps through edits elsewhere, and cancels on overlapping edits', () => {
    let s = mk().update({ effects: showProposal.of(P) }).state;
    expect(s.field(proposalField)).toEqual(P);
    s = s.update({ changes: { from: 0, insert: 'FADE IN:\n\n' } }).state;
    expect(s.field(proposalField)).toMatchObject({ from: 24, to: 35 });
    s = s.update({ changes: { from: 26, insert: 'x' } }).state;
    expect(s.field(proposalField)).toBeNull();
  });
  it('accepts as one change, inserts below, or rejects', () => {
    const v = viewOf(mk().update({ effects: showProposal.of(P) }).state);
    expect(acceptProposal(v)).toBe(true);
    expect(v.state.doc.toString()).toBe(DOC.replace('Mara waits.', 'Mara paces.'));
    expect(v.state.field(proposalField)).toBeNull();

    const w = viewOf(mk().update({ effects: showProposal.of({ ...P, mode: 'insert', from: 25, to: 25, text: 'She sits.' }) }).state);
    expect(insertProposal(w)).toBe(true);
    expect(w.state.doc.toString()).toBe(DOC.replace('Mara waits.', 'Mara waits.\n\nShe sits.'));

    const r = viewOf(mk().update({ effects: showProposal.of(P) }).state);
    expect(rejectProposal(r)).toBe(true);
    expect(r.state.doc.toString()).toBe(DOC);
    expect(acceptProposal(r)).toBe(false);
  });
  it('renders a widget whose Accept button applies the edit', () => {
    const parent = document.createElement('div');
    parent.style.height = '600px';
    document.body.appendChild(parent);
    const view = new EditorView({ state: mk(), parent });
    view.dispatch({ effects: showProposal.of(P) });
    expect(parent.querySelector('.sw-del')?.textContent).toBe('Mara waits.');
    expect(parent.querySelector('.sw-proposal-text')?.textContent).toBe('Mara paces.');
    const accept = [...parent.querySelectorAll('.sw-proposal button')].find((b) => b.textContent === 'Accept');
    accept.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    expect(view.state.doc.toString()).toContain('Mara paces.');
    view.destroy();
  });
});

describe('editorContext', () => {
  it('reports the scene around the cursor and the selection', () => {
    const ctx = editorContext(mk(DOC, EditorSelection.range(14, 18)));
    expect(ctx.scene).toEqual({ from: 0, to: 25, text: 'INT. A - DAY\n\nMara waits.' });
    expect(ctx.selection).toEqual({ from: 14, to: 18, text: 'Mara' });
    expect(ctx.cursorLine).toBe(2);
    expect(ctx.elements.length).toBeGreaterThan(0);
  });
});

describe('isStaleProposal', () => {
  const s = mk();
  const orig = DOC.slice(14, 25);
  it('is fresh when the range still holds the original, stale once edited', () => {
    expect(isStaleProposal(s, { from: 14, to: 25, original: orig })).toBe(false);
    expect(isStaleProposal(mk('INT. A - DAY\n\nMara sits down.\n\nINT. B - DAY\n\nGo.'), { from: 14, to: 25, original: orig })).toBe(true);
  });
  it('checks insert proposals against anchorFrom', () => {
    expect(isStaleProposal(s, { from: 25, to: 25, anchorFrom: 14, original: orig })).toBe(false);
    expect(isStaleProposal(s, { from: 25, to: 25, anchorFrom: 13, original: orig })).toBe(true);
  });
  it('is stale when out of range', () => {
    expect(isStaleProposal(s, { from: 0, to: 9999, original: orig })).toBe(true);
  });
});
