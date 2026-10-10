import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';

vi.mock('../components/TemplatePicker', () => ({
  TemplateInsertDialog: ({ onInsert, onClose }: { onInsert: (md: string) => void; onClose: () => void }) => (
    <button
      type="button"
      onClick={() => {
        onInsert('## Inserted heading\n');
        onClose();
      }}
    >
      fake insert
    </button>
  ),
}));

describe('RichMarkdownEditor /template', () => {
  it('opens the template dialog on the slash event and inserts the rendered body', async () => {
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor markdown="start" onSave={() => {}} jotId="t" onEditorReady={(e) => {
        editor = e;
      }} />,
    );
    expect(screen.queryByRole('button', { name: 'fake insert' })).toBeNull();
    act(() => {
      (editor as unknown as { emit: (event: string) => void }).emit('gb:slash:template');
    });
    fireEvent.click(await screen.findByRole('button', { name: 'fake insert' }));
    await waitFor(() => expect(editor!.getHTML()).toContain('<h2>Inserted heading</h2>'));
    expect(screen.queryByRole('button', { name: 'fake insert' })).toBeNull();
  });
});
