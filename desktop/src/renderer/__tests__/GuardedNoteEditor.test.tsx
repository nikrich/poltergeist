import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import { GuardedNoteEditor, type GuardHandle } from '../components/GuardedNoteEditor';
import { ApiError } from '../lib/api/client';
import { useNavigation, type NavigationScope } from '../stores/navigation';
import { useNoteView } from '../stores/note-view';
import { RESTORE_BLOCKED } from '../lib/use-guarded-save';

// Pass-through wrapper that records every onSave the editor is rendered with,
// so a test can call a replaced instance's handler after a remount.
const editorSaves = vi.hoisted(() => [] as Array<(body: string) => void>);
vi.mock('../components/RichMarkdownEditor', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../components/RichMarkdownEditor')>();
  const { createElement } = await import('react');
  return {
    ...mod,
    RichMarkdownEditor: (props: Parameters<typeof mod.RichMarkdownEditor>[0]) => {
      editorSaves.push(props.onSave);
      return createElement(mod.RichMarkdownEditor, props);
    },
  };
});

const E1 = 'aaaaaaaaaaaaaaaa';
const E2 = 'cccccccccccccccc';

function setup(
  send: ReturnType<typeof vi.fn>,
  fetchLatest: ReturnType<typeof vi.fn>,
  guardRef?: React.MutableRefObject<GuardHandle | null>,
  navigationScope?: NavigationScope,
) {
  let editor: Editor | undefined;
  const view = render(
    <GuardedNoteEditor
      initialBody="original line"
      initialEtag={E1}
      send={send}
      fetchLatest={fetchLatest}
      guardRef={guardRef}
      navigationScope={navigationScope}
      editorProps={{
        jotId: 'n.md',
        debounceMs: 10,
        onEditorReady: (e) => {
          editor = e;
        },
      }}
    />,
  );
  const getEditor = () => editor;
  return Object.assign(getEditor, { unmount: view.unmount });
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

  it('guardRef.hasConflict() is false before a 409 and true after', async () => {
    const send = vi.fn().mockRejectedValueOnce(new ApiError('changed', 409));
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'their edit', etag: E2 });
    const guardRef: React.MutableRefObject<GuardHandle | null> = { current: null };
    const getEditor = setup(send, fetchLatest, guardRef);
    await waitFor(() => expect(getEditor()).toBeDefined());
    expect(guardRef.current?.hasConflict()).toBe(false);
    await typeTail(getEditor);
    await screen.findByRole('alert');
    expect(guardRef.current?.hasConflict()).toBe(true);
  });

  it('restore reloads the editor with the restored text and chains its etag', async () => {
    const send = vi.fn().mockResolvedValue({ etag: 'eeeeeeeeeeeeeeee' });
    const guardRef = { current: null } as React.MutableRefObject<GuardHandle | null>;
    const getEditor = setup(send, vi.fn(), guardRef);
    await waitFor(() => expect(guardRef.current).not.toBeNull());
    await act(async () => {
      await guardRef.current!.restore(async () => ({ body: 'restored text', etag: E2 }));
    });
    await screen.findByText('restored text');
    await typeTail(getEditor);
    await waitFor(() =>
      expect(send).toHaveBeenLastCalledWith(expect.stringContaining('restored text'), E2),
    );
  });

  it('an autosave scheduled before a restore never overwrites it', async () => {
    const send = vi.fn().mockResolvedValue({ etag: 'eeeeeeeeeeeeeeee' });
    const guardRef = { current: null } as React.MutableRefObject<GuardHandle | null>;
    const getEditor = setup(send, vi.fn(), guardRef);
    await typeTail(getEditor); // debounced save pending (10 ms)
    await act(async () => {
      await guardRef.current!.restore(async () => ({ body: 'restored text', etag: E2 }));
    });
    await screen.findByText('restored text');
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60));
    });
    // Nothing based on the pre-restore text may be sent on the restored etag.
    expect(send.mock.calls.filter(([, ifMatch]) => ifMatch === E2)).toEqual([]);
  });

  it("a replaced editor instance's save after a restore sends nothing", async () => {
    // The window liveNonce covers: the old instance's debounce fires after
    // runExclusive released but before React committed the remount.
    const send = vi.fn().mockResolvedValue({ etag: 'eeeeeeeeeeeeeeee' });
    const guardRef = { current: null } as React.MutableRefObject<GuardHandle | null>;
    const getEditor = setup(send, vi.fn(), guardRef);
    await waitFor(() => expect(getEditor()).toBeDefined());
    const staleSave = editorSaves[editorSaves.length - 1]!;
    await act(async () => {
      await guardRef.current!.restore(async () => ({ body: 'restored text', etag: E2 }));
    });
    await screen.findByText('restored text');
    await act(async () => {
      staleSave('pre-restore text');
      await new Promise((r) => setTimeout(r, 60));
    });
    expect(send).not.toHaveBeenCalled();
  });

  it('restore is refused while the conflict banner is up', async () => {
    const send = vi.fn().mockRejectedValueOnce(new ApiError('changed', 409));
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'their edit', etag: E2 });
    const guardRef = { current: null } as React.MutableRefObject<GuardHandle | null>;
    const getEditor = setup(send, fetchLatest, guardRef);
    await typeTail(getEditor);
    await screen.findByRole('alert');
    const perform = vi.fn();
    await expect(guardRef.current!.restore(perform)).rejects.toThrow(RESTORE_BLOCKED);
    expect(perform).not.toHaveBeenCalled();
  });
});

describe('GuardedNoteEditor navigation guard', () => {
  beforeEach(() => {
    useNavigation.setState({ active: 'jots' });
    useNoteView.setState({ path: 'n.md' });
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  async function conflicted(scope: NavigationScope, send = vi.fn().mockRejectedValueOnce(new ApiError('changed', 409))) {
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'their edit', etag: E2 });
    const getEditor = setup(send, fetchLatest, undefined, scope);
    await typeTail(getEditor);
    await screen.findByRole('alert');
    return getEditor;
  }

  it('does not prompt on a screen change while no conflict is pending', async () => {
    const getEditor = setup(vi.fn().mockResolvedValue({ etag: E2 }), vi.fn(), undefined, 'screen');
    await waitFor(() => expect(getEditor()).toBeDefined());
    const confirm = vi.spyOn(window, 'confirm');
    act(() => useNavigation.getState().setActive('today'));
    expect(confirm).not.toHaveBeenCalled();
    expect(useNavigation.getState().active).toBe('today');
  });

  it('asks before a screen change under the conflict banner; cancel keeps screen and text', async () => {
    await conflicted('screen');
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    act(() => useNavigation.getState().setActive('today'));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm.mock.calls[0]![0]).toMatch(/changed outside the editor.*Discard your text\?/);
    expect(useNavigation.getState().active).toBe('jots');
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/my tail/)).toBeInTheDocument();

    confirm.mockReturnValue(true);
    act(() => useNavigation.getState().setActive('today'));
    expect(useNavigation.getState().active).toBe('today');
  });

  it('re-selecting the current screen does not prompt', async () => {
    await conflicted('screen');
    const confirm = vi.spyOn(window, 'confirm');
    act(() => useNavigation.getState().setActive('jots'));
    expect(confirm).not.toHaveBeenCalled();
  });

  it('a screen-scoped guard does not prompt on a note open (and vice versa)', async () => {
    await conflicted('screen');
    const confirm = vi.spyOn(window, 'confirm');
    act(() => useNoteView.getState().open('other.md'));
    expect(confirm).not.toHaveBeenCalled();
    expect(useNoteView.getState().path).toBe('other.md');
  });

  it('asks before opening another note under the conflict banner (note scope)', async () => {
    await conflicted('note');
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    act(() => useNavigation.getState().setActive('today'));
    expect(confirm).not.toHaveBeenCalled();
    act(() => useNoteView.getState().open('other.md'));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(useNoteView.getState().path).toBe('n.md');
    expect(screen.getByText(/my tail/)).toBeInTheDocument();
    confirm.mockReturnValue(true);
    act(() => useNoteView.getState().open('other.md'));
    expect(useNoteView.getState().path).toBe('other.md');
  });

  it('unregisters the guard on unmount: no stale prompt afterwards', async () => {
    const getEditor = await conflicted('screen');
    getEditor.unmount();
    const confirm = vi.spyOn(window, 'confirm');
    act(() => useNavigation.getState().setActive('today'));
    expect(confirm).not.toHaveBeenCalled();
    expect(useNavigation.getState().active).toBe('today');
  });

  it('unregisters the guard once the conflict is resolved', async () => {
    const send = vi
      .fn()
      .mockRejectedValueOnce(new ApiError('changed', 409))
      .mockResolvedValue({ etag: 'dddddddddddddddd' });
    await conflicted('screen', send);
    fireEvent.click(screen.getByRole('button', { name: 'keep mine' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
    const confirm = vi.spyOn(window, 'confirm');
    act(() => useNavigation.getState().setActive('today'));
    expect(confirm).not.toHaveBeenCalled();
    expect(useNavigation.getState().active).toBe('today');
  });
});
