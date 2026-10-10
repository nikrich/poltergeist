import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { Editor } from '@tiptap/core';
import type { EditorView } from '@tiptap/pm/view';
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
  path: '20-contexts/work/notes/synced.md',
  title: 'synced note',
  body: '# synced\n\nfrom gmail',
  frontmatter: { source: 'gmail', context: 'work' },
};

const manualNote: Note = {
  path: '20-contexts/work/notes/manual-20260609T090000-x.md',
  title: 'manual note',
  body: 'hand-written',
  frontmatter: { source: 'manual', context: 'work' },
};

afterEach(() => {
  vi.restoreAllMocks();
});

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

  it('clicking a wikilink in the note body opens the target note via useNoteView.open', async () => {
    const wikilinkNote: Note = {
      path: '20-contexts/work/notes/with-links.md',
      title: 'has links',
      body: 'See [[20-contexts/personal/_profile]] for context.',
      frontmatter: { source: 'manual', context: 'work' },
    };
    apiRequest.mockResolvedValue({ ok: true, data: wikilinkNote });
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
    act(() => useNoteView.getState().open(wikilinkNote.path));
    await waitFor(() => expect(editor).toBeDefined());
    // Simulate clicking inside the wikilink text
    act(() => {
      const doc = editor!.state.doc;
      let wikilinkPos = -1;
      doc.descendants((node, pos) => {
        if (node.isText && node.text && node.text.includes('[[')) {
          const offset = node.text.indexOf('[[');
          wikilinkPos = pos + offset + 5;
          return false;
        }
      });
      expect(wikilinkPos).toBeGreaterThan(0);
      editor!.view.someProp('handleClick', (f: (view: EditorView, pos: number, event: MouseEvent) => boolean | void) =>
        f(editor!.view, wikilinkPos, new MouseEvent('click')),
      );
    });
    // The store should now point to the linked note
    expect(useNoteView.getState().path).toBe('20-contexts/personal/_profile.md');
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

  it('sends the note etag as If-Match on autosave', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { ...syncedNote, etag: '0123456789abcdef' } });
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
    await waitFor(
      () =>
        expect(apiRequest).toHaveBeenCalledWith(
          'PATCH',
          '/v1/notes/body',
          { path: syncedNote.path, body: expect.stringContaining('edited tail') },
          { ifMatch: '0123456789abcdef' },
        ),
      { timeout: 3000 },
    );
  });

  it('closing under the conflict banner asks first and keeps the editor when declined', async () => {
    apiRequest.mockImplementation(async (method: string) => {
      if (method === 'PATCH') return { ok: false, status: 409, error: 'note changed' };
      return { ok: true, data: { ...manualNote, body: 'their edit', etag: 'bbbbbbbbbbbbbbbb' } };
    });
    apiRequest.mockResolvedValueOnce({ ok: true, data: { ...manualNote, etag: 'aaaaaaaaaaaaaaaa' } });
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
    act(() => useNoteView.getState().open(manualNote.path));
    await waitFor(() => expect(editor).toBeDefined());
    act(() => {
      editor!.commands.insertContentAt(editor!.state.doc.content.size, 'my tail');
    });
    await screen.findByRole('alert', {}, { timeout: 3000 });

    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    fireEvent.keyDown(window, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: 'close' }));
    fireEvent.click(screen.getByRole('dialog', { name: 'note viewer' }));
    expect(confirm).toHaveBeenCalledTimes(3);
    expect(useNoteView.getState().path).toBe(manualNote.path);
    expect(screen.getByRole('alert')).toBeInTheDocument();

    confirm.mockReturnValue(true);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(useNoteView.getState().path).toBeNull();
  });

  it('opening another note from outside NoteView under the conflict banner asks first', async () => {
    apiRequest.mockImplementation(async (method: string, path: string) => {
      if (method === 'PATCH') return { ok: false, status: 409, error: 'note changed' };
      if (path.startsWith('/v1/vault/backlinks')) {
        return {
          ok: true,
          data: {
            items: [{ path: '20-contexts/work/notes/standup.md', title: 'Standup', context: 'work', snippet: '' }],
            indexing: false,
          },
        };
      }
      return { ok: true, data: { ...manualNote, body: 'their edit', etag: 'bbbbbbbbbbbbbbbb' } };
    });
    apiRequest.mockResolvedValueOnce({ ok: true, data: { ...manualNote, etag: 'aaaaaaaaaaaaaaaa' } });
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
    act(() => useNoteView.getState().open(manualNote.path));
    await waitFor(() => expect(editor).toBeDefined());
    act(() => {
      editor!.commands.insertContentAt(editor!.state.doc.content.size, 'my tail');
    });
    await screen.findByRole('alert', {}, { timeout: 3000 });

    // A search result / backlink / chat link elsewhere calls the store directly.
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    act(() => useNoteView.getState().open(syncedNote.path));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm.mock.calls[0]![0]).toMatch(/Discard your text\?/);
    expect(useNoteView.getState().path).toBe(manualNote.path);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/my tail/)).toBeInTheDocument();

    // In-view links ask exactly once too (no double prompt).
    act(() => {
      screen.getByText('Standup').click();
    });
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(useNoteView.getState().path).toBe(manualNote.path);

    confirm.mockReturnValue(true);
    act(() => useNoteView.getState().open(syncedNote.path));
    expect(useNoteView.getState().path).toBe(syncedNote.path);
  });

  it('shows backlinks for the open note and opens one on click', async () => {
    apiRequest.mockImplementation(async (_method: string, path: string) => {
      if (path.startsWith('/v1/vault/backlinks')) {
        return {
          ok: true,
          data: {
            items: [
              {
                path: '20-contexts/work/notes/standup.md',
                title: 'Standup',
                context: 'work',
                snippet: 'see [[20-contexts/work/notes/manual-20260609T090000-x|manual note]]',
              },
            ],
            indexing: false,
          },
        };
      }
      return { ok: true, data: manualNote };
    });
    render(withQuery(<NoteView />));
    act(() => useNoteView.getState().open(manualNote.path));
    expect(await screen.findByText('Standup')).toBeInTheDocument();
    expect(screen.getByText('see manual note')).toBeInTheDocument();
    act(() => {
      screen.getByText('Standup').click();
    });
    expect(useNoteView.getState().path).toBe('20-contexts/work/notes/standup.md');
  });
});
