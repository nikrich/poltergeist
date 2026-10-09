import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import { GuardedNoteEditor } from '../components/GuardedNoteEditor';
import { ApiError } from '../lib/api/client';

const E1 = 'aaaaaaaaaaaaaaaa';
const E2 = 'cccccccccccccccc';

function setup(send: ReturnType<typeof vi.fn>, fetchLatest: ReturnType<typeof vi.fn>) {
  let editor: Editor | undefined;
  render(
    <GuardedNoteEditor
      initialBody="original line"
      initialEtag={E1}
      send={send}
      fetchLatest={fetchLatest}
      editorProps={{
        jotId: 'n.md',
        debounceMs: 10,
        onEditorReady: (e) => {
          editor = e;
        },
      }}
    />,
  );
  return () => editor;
}

async function typeTail(getEditor: () => Editor | undefined) {
  await waitFor(() => expect(getEditor()).toBeDefined());
  act(() => {
    const ed = getEditor()!;
    ed.commands.insertContentAt(ed.state.doc.content.size, 'my tail');
  });
}

describe('GuardedNoteEditor', () => {
  it('shows the banner on 409 and the diff of theirs against mine', async () => {
    const send = vi.fn().mockRejectedValueOnce(new ApiError('changed', 409));
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'their edit', etag: E2 });
    const getEditor = setup(send, fetchLatest);
    await typeTail(getEditor);
    await screen.findByRole('alert');
    expect(screen.getByText(/This note changed outside the editor/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'view changes' }));
    const diff = screen.getByTestId('conflict-diff');
    expect(diff).toHaveTextContent('their edit');
    expect(diff).toHaveTextContent('my tail');
  });

  it('keep mine overwrites using the fresh etag and clears the banner', async () => {
    const send = vi
      .fn()
      .mockRejectedValueOnce(new ApiError('changed', 409))
      .mockResolvedValue({ etag: 'dddddddddddddddd' });
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'their edit', etag: E2 });
    const getEditor = setup(send, fetchLatest);
    await typeTail(getEditor);
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'keep mine' }));
    await waitFor(() =>
      expect(send).toHaveBeenLastCalledWith(expect.stringContaining('my tail'), E2),
    );
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('keep theirs reloads the editor with their text', async () => {
    const send = vi.fn().mockRejectedValueOnce(new ApiError('changed', 409));
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'their edit', etag: E2 });
    const getEditor = setup(send, fetchLatest);
    await typeTail(getEditor);
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'keep theirs' }));
    await screen.findByText('their edit');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(/my tail/)).toBeNull();
  });

  it('when their version cannot be re-read, only keep mine is offered', async () => {
    const send = vi
      .fn()
      .mockRejectedValueOnce(new ApiError('changed', 409))
      .mockResolvedValue({ etag: 'dddddddddddddddd' });
    const fetchLatest = vi
      .fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue({ body: 'their edit', etag: E2 });
    const onSaveError = vi.fn();
    let editor: Editor | undefined;
    render(
      <GuardedNoteEditor
        initialBody="original line"
        initialEtag={E1}
        send={send}
        fetchLatest={fetchLatest}
        onSaveError={onSaveError}
        editorProps={{
          jotId: 'n.md',
          debounceMs: 10,
          onEditorReady: (e) => {
            editor = e;
          },
        }}
      />,
    );
    await typeTail(() => editor);
    await screen.findByRole('alert');
    expect(screen.getByText(/could not be loaded/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'keep theirs' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'view changes' })).toBeNull();
    expect(screen.queryByTestId('conflict-diff')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'keep mine' }));
    await waitFor(() =>
      expect(send).toHaveBeenLastCalledWith(expect.stringContaining('my tail'), E2),
    );
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });
});
