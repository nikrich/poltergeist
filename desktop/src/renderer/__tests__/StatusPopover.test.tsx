import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';
import { emitGb } from '../lib/editor/events';
import { findNodePos } from './helpers/editor';

vi.useFakeTimers();

function setup(markdown: string) {
  const onSave = vi.fn();
  let editor: Editor | undefined;
  render(
    <RichMarkdownEditor markdown={markdown} onSave={onSave} jotId="t" onEditorReady={(e) => { editor = e; }} />,
  );
  return { onSave, editor: () => editor! };
}

function openFor(editor: Editor) {
  const pos = findNodePos(editor, (n) => n.type.name === 'status');
  act(() => emitGb(editor, 'gb:status:edit', { pos }));
}

describe('StatusPopover', () => {
  beforeEach(() => vi.clearAllTimers());

  it('opens on gb:status:edit with the current label', () => {
    const { editor } = setup('x `status:To do/grey`');
    openFor(editor());
    expect(screen.getByRole('dialog', { name: 'edit status' })).toBeInTheDocument();
    expect(screen.getByLabelText('status label')).toHaveValue('To do');
    expect(screen.getByLabelText('colour grey')).toHaveAttribute('aria-pressed', 'true');
  });

  it('Enter saves label + colour into markdown and closes', () => {
    const { editor, onSave } = setup('x `status:To do/grey`');
    openFor(editor());
    fireEvent.change(screen.getByLabelText('status label'), { target: { value: 'Done' } });
    fireEvent.click(screen.getByLabelText('colour green'));
    fireEvent.keyDown(screen.getByLabelText('status label'), { key: 'Enter' });
    act(() => { vi.advanceTimersByTime(1000); });
    expect(onSave.mock.calls.at(-1)?.[0]).toBe('x `status:Done/green`');
    expect(screen.queryByRole('dialog', { name: 'edit status' })).toBeNull();
  });

  it('does not save an empty label and stays open', () => {
    const { editor, onSave } = setup('x `status:To do/grey`');
    openFor(editor());
    fireEvent.change(screen.getByLabelText('status label'), { target: { value: '   ' } });
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    act(() => { vi.advanceTimersByTime(1000); });
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog', { name: 'edit status' })).toBeInTheDocument();
  });

  it('strips backticks from the label so the code span stays simple', () => {
    const { editor, onSave } = setup('x `status:To do/grey`');
    openFor(editor());
    fireEvent.change(screen.getByLabelText('status label'), { target: { value: 'a`b' } });
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    act(() => { vi.advanceTimersByTime(1000); });
    expect(onSave.mock.calls.at(-1)?.[0]).toBe('x `status:ab/grey`');
  });

  it('Escape closes without changing the document', () => {
    const { editor, onSave } = setup('x `status:To do/grey`');
    openFor(editor());
    fireEvent.keyDown(screen.getByLabelText('status label'), { key: 'Escape' });
    act(() => { vi.advanceTimersByTime(1000); });
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog', { name: 'edit status' })).toBeNull();
  });
});
