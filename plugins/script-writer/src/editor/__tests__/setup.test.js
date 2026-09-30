// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { completionStatus } from '@codemirror/autocomplete';
import { enter } from '../commands.js';
import { createEditor, jumpToLine, setFocusMode } from '../setup.js';

describe('createEditor', () => {
  it('decorates lines by element type and reports changes', () => {
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    const changes = [];
    const view = createEditor({ parent, doc: 'INT. HOUSE - DAY\n\nMARA\nHi.', onDocChange: (t) => changes.push(t) });
    const classes = [...parent.querySelectorAll('.cm-line')].map((l) => l.className);
    expect(classes[0]).toContain('sw-l-scene_heading');
    expect(classes[2]).toContain('sw-l-character');
    expect(classes[3]).toContain('sw-l-dialogue');
    view.dispatch({ changes: { from: view.state.doc.length, insert: '!' } });
    expect(changes.at(-1)).toBe('INT. HOUSE - DAY\n\nMARA\nHi.!');
    jumpToLine(view, 2);
    expect(view.state.doc.lineAt(view.state.selection.main.head).number).toBe(3);
    setFocusMode(view, true);
    expect(parent.querySelectorAll('.sw-dim').length).toBeGreaterThan(0);
    view.destroy();
  });

  it('Enter on an empty hinted character line resets it to action', () => {
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    const view = createEditor({ parent, doc: 'MARA\nHi.' });
    view.dispatch({ selection: { anchor: view.state.doc.length } });
    const run = () => enter({ state: view.state, dispatch: view.dispatch.bind(view) });
    expect(run()).toBe(true);
    expect(view.state.doc.toString()).toBe('MARA\nHi.\n\n');
    expect(completionStatus(view.state)).toBe(null);
    expect(run()).toBe(true);
    expect(view.state.doc.toString()).toBe('MARA\nHi.\n\n');
    const last = [...parent.querySelectorAll('.cm-line')].at(-1);
    expect(last.className).toContain('sw-l-action');
    view.destroy();
  });

  it('reports the new line type after a hint-only Enter', () => {
    const parent = document.createElement('div');
    document.body.appendChild(parent);
    const calls = [];
    const view = createEditor({ parent, doc: 'MARA\nHi.', onCursorLine: (l, t) => calls.push([l, t]) });
    view.dispatch({ selection: { anchor: view.state.doc.length } });
    enter({ state: view.state, dispatch: view.dispatch.bind(view) });
    enter({ state: view.state, dispatch: view.dispatch.bind(view) });
    expect(calls.at(-1)[1]).toBe('action');
    view.destroy();
  });
});
