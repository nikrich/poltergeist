import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Editor } from '@tiptap/core';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { EditorToolbar } from '../components/EditorToolbar';

function makeEditor() {
  return new Editor({ extensions: buildEditorExtensions(), content: 'word' });
}

describe('EditorToolbar', () => {
  it('toggles bold on the current selection', () => {
    const editor = makeEditor();
    editor.commands.selectAll();
    render(<EditorToolbar editor={editor} onPhoto={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /bold/i }));
    expect(editor.isActive('bold')).toBe(true);
    editor.destroy();
  });

  it('invokes onPhoto when the photo button is clicked', () => {
    const editor = makeEditor();
    const onPhoto = vi.fn();
    render(<EditorToolbar editor={editor} onPhoto={onPhoto} />);
    fireEvent.click(screen.getByRole('button', { name: /photo/i }));
    expect(onPhoto).toHaveBeenCalledOnce();
    editor.destroy();
  });
});
