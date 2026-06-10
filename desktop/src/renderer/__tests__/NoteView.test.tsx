import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { Editor } from '@tiptap/core';
import { NoteView } from '../components/NoteView';
import { useNoteView } from '../stores/note-view';
import type { Note } from '../../shared/api-types';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  useNoteView.getState().close();
  window.gb = {
    ...window.gb,
    api: { request: apiRequest },
  };
});

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const syncedNote: Note = {
  path: '20-contexts/sanlam/notes/synced.md',
  title: 'synced note',
  body: '# synced\n\nfrom gmail',
  frontmatter: { source: 'gmail', context: 'sanlam' },
};

const manualNote: Note = {
  path: '20-contexts/sanlam/notes/manual-20260609T090000-x.md',
  title: 'manual note',
  body: 'hand-written',
  frontmatter: { source: 'manual', context: 'sanlam' },
};

describe('NoteView', () => {
  it('renders the note in the rich editor with the synced-note warning chip', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: syncedNote });
    render(withQuery(<NoteView />));
    act(() => useNoteView.getState().open(syncedNote.path));
    await screen.findByText('from gmail');
    expect(screen.getByTestId('rich-markdown-editor')).toBeInTheDocument();
    expect(
      screen.getByText(/synced note — edits may be overwritten by the next sync/),
    ).toBeInTheDocument();
  });

  it('shows no warning chip for manual notes', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: manualNote });
    render(withQuery(<NoteView />));
    act(() => useNoteView.getState().open(manualNote.path));
    await screen.findByText('hand-written');
    expect(screen.queryByText(/edits may be overwritten/)).toBeNull();
  });

  it('saves edits through PATCH /v1/notes/body', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: syncedNote });
    let editor: Editor | undefined;
    render(
      withQuery(
        <NoteView
          onEditorReady={(e) => {
            editor = e;
          }}
        />,
      ),
    );
    act(() => useNoteView.getState().open(syncedNote.path));
    await waitFor(() => expect(editor).toBeDefined());
    act(() => {
      editor!.commands.insertContentAt(editor!.state.doc.content.size, 'edited tail');
    });
    // Real timers in this file — the editor debounce is 1s.
    await waitFor(
      () =>
        expect(apiRequest).toHaveBeenCalledWith('PATCH', '/v1/notes/body', {
          path: syncedNote.path,
          body: expect.stringContaining('edited tail'),
        }),
      { timeout: 3000 },
    );
  });
});
