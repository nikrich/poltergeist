import { act, createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type React from 'react';
import type { Editor } from '@tiptap/core';
import { CellSelection } from '@tiptap/pm/tables';
import { RichMarkdownEditor, type EditorHandle } from '../components/RichMarkdownEditor';
import { getAiSuggestion } from '../lib/editor/ai-suggestion';
import { isMac } from '../lib/platform';
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
  it('⌘J opens the popover; without inlineAssist it does nothing', async () => {
    const { editor } = setup();
    pressModJ(editor());
    expect(await screen.findByRole('dialog', { name: 'inline ai' })).toBeInTheDocument();
  });

  it('is inert without the inlineAssist prop', () => {
    const { editor } = setup('alpha', { inlineAssist: undefined });
    pressModJ(editor());
    expect(screen.queryByRole('dialog', { name: 'inline ai' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'inline ai' })).toBeNull();
  });

  it('the toolbar ✦ button opens it', async () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'inline ai' }));
    expect(await screen.findByRole('dialog', { name: 'inline ai' })).toBeInTheDocument();
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
