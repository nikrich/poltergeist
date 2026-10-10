import { afterEach, describe, expect, it, vi } from 'vitest';
import { Editor } from '@tiptap/core';
import { buildEditorExtensions } from '../lib/editor/extensions';
import {
  READ_ALOUD_CLASS,
  attachReadAloudHighlight,
  currentHighlight,
  setReadAloudHighlight,
} from '../lib/read-aloud/highlight';

let editor: Editor | null = null;

function make(content: string, onUpdate = vi.fn()) {
  editor = new Editor({
    element: document.createElement('div'),
    extensions: buildEditorExtensions(),
    content,
    onUpdate,
  });
  return editor;
}

function highlighted(ed: Editor): string {
  return Array.from(ed.view.dom.querySelectorAll(`.${READ_ALOUD_CLASS}`))
    .map((n) => n.textContent)
    .join('');
}

afterEach(() => {
  editor?.destroy();
  editor = null;
});

describe('read-aloud highlight', () => {
  it('decorates the given range', () => {
    const ed = make('One. Two.');
    attachReadAloudHighlight(ed);
    setReadAloudHighlight(ed, { from: 6, to: 10 });
    expect(highlighted(ed)).toBe('Two.');
    expect(currentHighlight(ed)).toEqual({ from: 6, to: 10 });
  });

  it('null clears it', () => {
    const ed = make('One. Two.');
    attachReadAloudHighlight(ed);
    setReadAloudHighlight(ed, { from: 1, to: 5 });
    setReadAloudHighlight(ed, null);
    expect(highlighted(ed)).toBe('');
    expect(currentHighlight(ed)).toBeNull();
  });

  it('never changes the doc, fires no update and adds no undo step', () => {
    const onUpdate = vi.fn();
    const ed = make('One. Two.', onUpdate);
    attachReadAloudHighlight(ed);
    const before = ed.getJSON();
    setReadAloudHighlight(ed, { from: 1, to: 5 });
    expect(ed.getJSON()).toEqual(before);
    expect(onUpdate).not.toHaveBeenCalled();
    expect(ed.can().undo()).toBe(false);
  });

  it('maps the highlight through edits', () => {
    const ed = make('One. Two.');
    attachReadAloudHighlight(ed);
    setReadAloudHighlight(ed, { from: 6, to: 10 });
    ed.view.dispatch(ed.state.tr.insertText('New. ', 1));
    expect(highlighted(ed)).toBe('Two.');
  });

  it('clamps out-of-range ranges instead of throwing', () => {
    const ed = make('One.');
    attachReadAloudHighlight(ed);
    expect(() => setReadAloudHighlight(ed, { from: 3, to: 999 })).not.toThrow();
    expect(highlighted(ed)).toBe('e.');
    expect(() => setReadAloudHighlight(ed, { from: 999, to: 1200 })).not.toThrow();
    expect(highlighted(ed)).toBe('');
  });

  it('attach is idempotent and detach removes the plugin', () => {
    const ed = make('One. Two.');
    const detach = attachReadAloudHighlight(ed);
    attachReadAloudHighlight(ed);
    setReadAloudHighlight(ed, { from: 1, to: 5 });
    expect(highlighted(ed)).toBe('One.');
    detach();
    expect(highlighted(ed)).toBe('');
    expect(() => setReadAloudHighlight(ed, { from: 1, to: 5 })).not.toThrow();
    expect(highlighted(ed)).toBe('');
  });

  it('is safe after the editor is destroyed', () => {
    const ed = make('One.');
    const detach = attachReadAloudHighlight(ed);
    ed.destroy();
    editor = null;
    expect(() => setReadAloudHighlight(ed, { from: 1, to: 2 })).not.toThrow();
    expect(() => detach()).not.toThrow();
  });
});
