import { act, createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type React from 'react';
import type { Editor } from '@tiptap/core';
import { CellSelection } from '@tiptap/pm/tables';
import { RichMarkdownEditor, type EditorHandle } from '../components/RichMarkdownEditor';
import { getAiSuggestion } from '../lib/editor/ai-suggestion';
import { isMac } from '../lib/platform';
import { shortcutLabel } from '../lib/editor-shortcuts';
import { useToasts } from '../stores/toast';
import type { DocsAssistEvent, DocsAssistRequest } from '../../shared/api-types';
import { markdownOf, textPos } from './helpers/editor';

type Payload = { key?: string; jotId: string; event: DocsAssistEvent };
let listener: ((p: Payload) => void) | null;
let assist: ReturnType<typeof vi.fn>;
const mod = isMac ? { metaKey: true } : { ctrlKey: true };

// jsdom has no layout: the accept transaction's scrollIntoView reaches
// ProseMirror's coordsAtPos, which needs Range rects.
const emptyRect = { x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 } as DOMRect;
if (!Range.prototype.getClientRects) {
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => ({ ...emptyRect, toJSON: () => emptyRect });
}

beforeEach(() => {
  listener = null;
  assist = vi.fn().mockResolvedValue({ ok: true });
  window.gb = {
    ...window.gb,
    docs: { ...window.gb.docs, assist, assistStop: vi.fn().mockResolvedValue({ ok: true }) },
    on: ((channel: string, l: (p: Payload) => void) => {
      if (channel === 'docs:event') listener = l;
      return () => {
        if (listener === l) listener = null;
      };
    }) as typeof window.gb.on,
  };
});

afterEach(() => vi.restoreAllMocks());

function setup(md = 'alpha beta gamma', extra: Partial<React.ComponentProps<typeof RichMarkdownEditor>> = {}) {
  const onSave = vi.fn();
  const onAccept = vi.fn();
  let editor!: Editor;
  const handleRef = { current: null } as React.MutableRefObject<EditorHandle | null>;
  render(
    <RichMarkdownEditor
      markdown={md}
      onSave={onSave}
      jotId="j1"
      debounceMs={60_000}
      handleRef={handleRef}
      onEditorReady={(e) => {
        editor = e;
      }}
      inlineAssist={{ target: { jot_id: 'j1' }, onAccept }}
      {...extra}
    />,
  );
  return { onSave, onAccept, handleRef, editor: () => editor };
}

function select(editor: Editor, text: string) {
  const from = textPos(editor, text);
  act(() => {
    editor.commands.setTextSelection({ from, to: from + text.length });
  });
}

const openInsert = () => fireEvent.click(screen.getByRole('button', { name: 'insert' }));

function pressModJ(editor: Editor) {
  fireEvent.keyDown(editor.view.dom, { key: 'j', ...mod });
}

function lastRequest(): DocsAssistRequest {
  return assist.mock.calls[assist.mock.calls.length - 1]![0] as DocsAssistRequest;
}

function fire(event: DocsAssistEvent) {
  const key = lastRequest().stream_id!;
  act(() => listener?.({ key, jotId: key, event }));
}

async function polishTo(editor: Editor, word: string, answer: string) {
  select(editor, word);
  pressModJ(editor);
  fireEvent.click(await screen.findByRole('button', { name: 'polish' }));
  fire({ type: 'done', text: answer });
}

describe('RichMarkdownEditor inline ai', () => {
  it('⌘J opens the popover', async () => {
    const { editor } = setup();
    pressModJ(editor());
    expect(await screen.findByRole('dialog', { name: 'inline ai' })).toBeInTheDocument();
  });

  it('is inert without the inlineAssist prop', () => {
    const { editor } = setup('alpha', { inlineAssist: undefined });
    pressModJ(editor());
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
    // A7: the one entry is the Insert menu's Ask AI row; absent without the prop.
    openInsert();
    expect(screen.queryByRole('menuitem', { name: /^Ask AI/ })).toBeNull();
    expect(screen.getByRole('menu')).toBeInTheDocument();
  });

  it('is off in a read-only editor even with the inlineAssist prop', () => {
    useToasts.setState({ toasts: [] });
    const { editor, handleRef } = setup('alpha beta gamma', { readOnly: true });
    select(editor(), 'beta');
    // A7: no formatting toolbar (so no Insert menu, no Ask AI row) when read-only.
    expect(screen.queryByRole('toolbar', { name: 'formatting' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'insert' })).toBeNull();
    expect(screen.queryByRole('menuitem', { name: /^Ask AI/ })).toBeNull();
    pressModJ(editor());
    let opened = true;
    let handedOff = true;
    act(() => {
      opened = handleRef.current!.startInlineAssist!();
      handedOff = handleRef.current!.startInlineAssist!({ mode: 'polish' });
    });
    expect(opened).toBe(false);
    expect(handedOff).toBe(false);
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
    expect(getAiSuggestion(editor())).toBeNull();
    expect(assist).not.toHaveBeenCalled();
    expect(useToasts.getState().toasts).toHaveLength(0);
  });

  it('the Insert menu\'s Ask AI row opens it (A7 toolbar)', async () => {
    const { editor, handleRef } = setup();
    select(editor(), 'beta');
    openInsert();
    const row = screen.getByRole('menuitem', { name: /^Ask AI/ });
    // A5 binds ⌘J to the same inline AI; the row shows it.
    expect(row).toHaveTextContent(shortcutLabel('inlineAi'));
    fireEvent.click(row);
    // A5's real popover, on the selection, through the same path as ⌘J.
    const dialog = await screen.findByRole('dialog', { name: 'inline ai' });
    expect(dialog).toBeInTheDocument();
    expect(screen.queryByRole('menu')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'polish' }));
    expect(lastRequest().selection).toBe('beta');
    // Same open popover the handle reports (startInlineAssist() → true, no restart).
    let again = false;
    act(() => {
      again = handleRef.current!.startInlineAssist!();
    });
    expect(again).toBe(true);
  });

  it('renders exactly one Ask AI affordance: no ✦ button, one sparkles row', () => {
    setup();
    const root = screen.getByTestId('rich-markdown-editor');
    expect(screen.queryByRole('button', { name: 'inline ai' })).toBeNull();
    expect(root.textContent).not.toContain('✦');
    expect(root.querySelectorAll('.lucide-sparkles')).toHaveLength(0);
    openInsert();
    expect(screen.getAllByRole('menuitem', { name: /Ask AI/ })).toHaveLength(1);
    expect(document.querySelectorAll('.lucide-sparkles')).toHaveLength(1);
    expect(document.body.textContent).not.toContain('✦');
  });

  it('source mode has no Ask AI path', () => {
    const { handleRef } = setup();
    fireEvent.click(screen.getByRole('button', { name: 'src' }));
    expect(screen.queryByRole('button', { name: 'insert' })).toBeNull();
    let opened = true;
    act(() => {
      opened = handleRef.current!.startInlineAssist!();
    });
    expect(opened).toBe(false);
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
  });

  it('accept saves at once and attributes only that save', async () => {
    const { editor, onSave, onAccept } = setup();
    await polishTo(editor(), 'beta', 'BETA');
    fireEvent.click(screen.getByRole('button', { name: /accept/ }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect((onSave.mock.calls[0]![0] as string).trim()).toBe('alpha BETA gamma');
    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(onAccept.mock.invocationCallOrder[0]!).toBeLessThan(onSave.mock.invocationCallOrder[0]!);
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
    act(() => {
      editor().commands.undo();
    });
    expect(markdownOf(editor())).toBe('alpha beta gamma');
  });

  it('pending user edits are saved as the user\'s before inline ai opens', () => {
    const { editor, onSave, onAccept } = setup();
    act(() => {
      editor().view.dispatch(editor().state.tr.insertText('typed ', 1));
    });
    expect(onSave).not.toHaveBeenCalled(); // still debounced
    pressModJ(editor());
    expect(onSave).toHaveBeenCalledTimes(1);
    expect((onSave.mock.calls[0]![0] as string).trim()).toBe('typed alpha beta gamma');
    expect(onAccept).not.toHaveBeenCalled();
  });

  it('an accept that changes nothing saves nothing and marks nothing', async () => {
    const { editor, onSave, onAccept } = setup();
    await polishTo(editor(), 'beta', 'beta');
    fireEvent.click(screen.getByRole('button', { name: /accept/ }));
    expect(onSave).not.toHaveBeenCalled();
    expect(onAccept).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
  });

  it('Esc in the editor rejects and is marked handled', async () => {
    const { editor, onSave } = setup();
    await polishTo(editor(), 'beta', 'BETA');
    const esc = createEvent.keyDown(editor().view.dom, { key: 'Escape' });
    fireEvent(editor().view.dom, esc);
    expect(esc.defaultPrevented).toBe(true);
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull());
    expect(getAiSuggestion(editor())).toBeNull();
    expect(markdownOf(editor())).toBe('alpha beta gamma');
    expect(onSave).not.toHaveBeenCalled();
  });

  it('Tab in the editor accepts a ready suggestion', async () => {
    const { editor, onSave } = setup();
    await polishTo(editor(), 'beta', 'BETA');
    fireEvent.keyDown(editor().view.dom, { key: 'Tab' });
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(markdownOf(editor())).toBe('alpha BETA gamma');
  });

  it('replaceWith clears an open suggestion', async () => {
    const { editor, handleRef } = setup();
    select(editor(), 'beta');
    pressModJ(editor());
    fireEvent.click(await screen.findByRole('button', { name: 'polish' }));
    expect(getAiSuggestion(editor())).not.toBeNull();
    act(() => handleRef.current!.replaceWith('new body', 'doc'));
    expect(getAiSuggestion(editor())).toBeNull();
    expect(markdownOf(editor())).toBe('new body');
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
  });

  it('startInlineAssist runs at once on the selection', async () => {
    const { editor, handleRef } = setup();
    select(editor(), 'beta');
    let ok = false;
    act(() => {
      ok = handleRef.current!.startInlineAssist!({ mode: 'polish', instruction: 'shorter' });
    });
    expect(ok).toBe(true);
    await waitFor(() => expect(assist).toHaveBeenCalledTimes(1));
    expect(lastRequest()).toMatchObject({ jot_id: 'j1', mode: 'polish', instruction: 'shorter', placement: 'selection' });
  });

  it('an edit while the popover waits for an action closes it (stale range)', async () => {
    const { editor, onSave, onAccept } = setup();
    select(editor(), 'beta');
    pressModJ(editor());
    await screen.findByRole('dialog', { name: 'inline ai' });
    act(() => {
      editor().view.dispatch(editor().state.tr.insertText('typed ', 1));
    });
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
    expect(markdownOf(editor())).toBe('typed alpha beta gamma');
    // The typing stays a pending user save; reopening flushes it unattributed.
    pressModJ(editor());
    expect(onSave).toHaveBeenCalledTimes(1);
    expect((onSave.mock.calls[0]![0] as string).trim()).toBe('typed alpha beta gamma');
    expect(onAccept).not.toHaveBeenCalled();
  });

  it('startInlineAssist with the popover open restarts it with the new action', async () => {
    const { editor, handleRef } = setup();
    select(editor(), 'beta');
    pressModJ(editor());
    fireEvent.click(await screen.findByRole('button', { name: 'polish' }));
    expect(assist).toHaveBeenCalledTimes(1);
    const first = lastRequest().stream_id;
    let ok = false;
    act(() => {
      ok = handleRef.current!.startInlineAssist!({ mode: 'expand' });
    });
    expect(ok).toBe(true);
    await waitFor(() => expect(assist).toHaveBeenCalledTimes(2));
    expect(lastRequest()).toMatchObject({ mode: 'expand', placement: 'selection' });
    expect(lastRequest().stream_id).not.toBe(first);
    expect(window.gb.docs.assistStop).toHaveBeenCalledWith(first);
    expect(screen.getAllByRole('dialog', { name: 'inline ai' })).toHaveLength(1);
  });

  it('a selection across table cells is refused', () => {
    const { editor } = setup('| a | b |\n| --- | --- |\n| one | two |');
    const cells: number[] = [];
    editor().state.doc.descendants((n, pos) => {
      if (n.type.name === 'tableCell' || n.type.name === 'tableHeader') cells.push(pos);
    });
    act(() => {
      editor().view.dispatch(
        editor().state.tr.setSelection(CellSelection.create(editor().state.doc, cells[2]!, cells[3]!)),
      );
    });
    pressModJ(editor());
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
    expect(useToasts.getState().toasts.map((t) => t.message)).toContain(
      'select text inside one table cell for inline ai',
    );
  });

  it('a cell selection handed over by startInlineAssist is refused without a toast', () => {
    const { editor, handleRef } = setup('| a | b |\n| --- | --- |\n| one | two |');
    useToasts.setState({ toasts: [] });
    const cells: number[] = [];
    editor().state.doc.descendants((n, pos) => {
      if (n.type.name === 'tableCell' || n.type.name === 'tableHeader') cells.push(pos);
    });
    act(() => {
      editor().view.dispatch(
        editor().state.tr.setSelection(CellSelection.create(editor().state.doc, cells[2]!, cells[3]!)),
      );
    });
    let ok = true;
    act(() => {
      ok = handleRef.current!.startInlineAssist!({ mode: 'polish' });
    });
    expect(ok).toBe(false);
    expect(useToasts.getState().toasts).toEqual([]);
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
    expect(assist).not.toHaveBeenCalled();
  });

  it('startInlineAssist() without an action opens the empty popover (Insert-menu "Ask AI")', async () => {
    const { editor, handleRef } = setup();
    select(editor(), 'beta');
    let ok = false;
    act(() => {
      ok = handleRef.current!.startInlineAssist!();
    });
    expect(ok).toBe(true);
    expect(await screen.findByRole('dialog', { name: 'inline ai' })).toBeInTheDocument();
    expect(assist).not.toHaveBeenCalled();
    // Already open: still true, and nothing restarts.
    act(() => {
      ok = handleRef.current!.startInlineAssist!();
    });
    expect(ok).toBe(true);
    expect(screen.getAllByRole('dialog', { name: 'inline ai' })).toHaveLength(1);
    expect(assist).not.toHaveBeenCalled();
  });

  it('switching to source mode clears an open suggestion', async () => {
    const { editor, onSave } = setup();
    select(editor(), 'beta');
    pressModJ(editor());
    fireEvent.click(await screen.findByRole('button', { name: 'polish' }));
    expect(getAiSuggestion(editor())).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'src' }));
    expect(getAiSuggestion(editor())).toBeNull();
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
    // Back in rich mode the stale popover must not come back.
    fireEvent.click(screen.getByRole('button', { name: 'rich' }));
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('a markdown prop resync clears an open suggestion and loads the new body', async () => {
    let editor!: Editor;
    const props = {
      onSave: vi.fn(),
      jotId: 'j1',
      debounceMs: 60_000,
      onEditorReady: (e: Editor) => {
        editor = e;
      },
      inlineAssist: { target: { jot_id: 'j1' } },
    };
    const { rerender } = render(<RichMarkdownEditor markdown="alpha beta gamma" {...props} />);
    select(editor, 'beta');
    pressModJ(editor);
    fireEvent.click(await screen.findByRole('button', { name: 'polish' }));
    expect(getAiSuggestion(editor)).not.toBeNull();
    rerender(<RichMarkdownEditor markdown="other note" {...props} />);
    expect(getAiSuggestion(editor)).toBeNull();
    expect(markdownOf(editor)).toBe('other note');
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
  });
});
