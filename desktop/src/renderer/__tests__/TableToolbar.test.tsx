import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import { TableToolbar } from '../components/TableToolbar';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';
import { makeEditor, markdownOf, textPos } from './helpers/editor';

const MD = 'intro\n\n| name | value |\n| --- | --- |\n| alpha | 1 |';

function inCell(editor: Editor, text: string) {
  act(() => {
    editor.commands.setTextSelection(textPos(editor, text));
  });
}

describe('TableToolbar', () => {
  it('is hidden outside tables and shown inside', () => {
    const editor = makeEditor(MD);
    render(<TableToolbar editor={editor} />);
    act(() => {
      editor.commands.setTextSelection(2);
    });
    expect(screen.queryByRole('toolbar', { name: 'table controls' })).toBeNull();
    inCell(editor, 'alpha');
    expect(screen.getByRole('toolbar', { name: 'table controls' })).toBeInTheDocument();
  });

  it('adds a row below the cursor row', () => {
    const editor = makeEditor(MD);
    render(<TableToolbar editor={editor} />);
    inCell(editor, 'alpha');
    fireEvent.click(screen.getByLabelText('add row below'));
    expect(markdownOf(editor)).toBe('intro\n\n| name | value |\n| --- | --- |\n| alpha | 1 |\n|  |  |');
  });

  it('deletes the cursor row', () => {
    const editor = makeEditor(MD + '\n| beta | 2 |');
    render(<TableToolbar editor={editor} />);
    inCell(editor, 'alpha');
    fireEvent.click(screen.getByLabelText('delete row'));
    expect(markdownOf(editor)).toBe('intro\n\n| name | value |\n| --- | --- |\n| beta | 2 |');
  });

  it('adds a column right of the cursor, then deletes another column', () => {
    const editor = makeEditor(MD);
    render(<TableToolbar editor={editor} />);
    inCell(editor, 'alpha');
    fireEvent.click(screen.getByLabelText('add column right'));
    expect(markdownOf(editor)).toBe('intro\n\n| name |  | value |\n| --- | --- | --- |\n| alpha |  | 1 |');
    inCell(editor, 'value');
    fireEvent.click(screen.getByLabelText('delete column'));
    expect(markdownOf(editor)).toBe('intro\n\n| name |  |\n| --- | --- |\n| alpha |  |');
  });

  it('aligns the column and marks the active alignment', () => {
    const editor = makeEditor(MD);
    render(<TableToolbar editor={editor} />);
    inCell(editor, 'alpha');
    fireEvent.click(screen.getByLabelText('align centre'));
    expect(markdownOf(editor)).toBe('intro\n\n| name | value |\n| :---: | --- |\n| alpha | 1 |');
    expect(screen.getByLabelText('align centre')).toHaveAttribute('aria-pressed', 'true');
  });

  it('toggles the header row and deletes the table', () => {
    const editor = makeEditor(MD);
    render(<TableToolbar editor={editor} />);
    inCell(editor, 'name');
    fireEvent.click(screen.getByLabelText('toggle header row'));
    expect(markdownOf(editor)).toBe('intro\n\n|  |  |\n| --- | --- |\n| name | value |\n| alpha | 1 |');
    inCell(editor, 'alpha');
    fireEvent.click(screen.getByLabelText('delete table'));
    expect(markdownOf(editor)).toBe('intro');
  });

  it('renders nothing in a read-only editor', () => {
    const editor = makeEditor(MD, false);
    render(<TableToolbar editor={editor} />);
    inCell(editor, 'alpha');
    expect(screen.queryByRole('toolbar', { name: 'table controls' })).toBeNull();
  });
});

describe('RichMarkdownEditor mounts the table toolbar', () => {
  it('shows table controls when the cursor is in a table', () => {
    let editor: Editor | undefined;
    render(<RichMarkdownEditor markdown={MD} onSave={() => {}} jotId="t" onEditorReady={(e) => { editor = e; }} />);
    inCell(editor!, 'alpha');
    expect(screen.getByRole('toolbar', { name: 'table controls' })).toBeInTheDocument();
  });
});
