import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type React from 'react';
import type { Editor } from '@tiptap/core';
import { GuardedNoteEditor, type GuardHandle } from '../components/GuardedNoteEditor';
import type { EditorHandle } from '../components/RichMarkdownEditor';
import { isMac } from '../lib/platform';
import type { DocsAssistEvent, DocsAssistRequest } from '../../shared/api-types';
import { textPos } from './helpers/editor';

// jsdom has no layout: the accept transaction's scrollIntoView reaches
// ProseMirror's coordsAtPos, which needs Range rects.
const emptyRect = { x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 } as DOMRect;
if (!Range.prototype.getClientRects) {
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => ({ ...emptyRect, toJSON: () => emptyRect });
}

type Payload = { key?: string; jotId: string; event: DocsAssistEvent };
let listener: ((p: Payload) => void) | null;
let assist: ReturnType<typeof vi.fn>;

beforeEach(() => {
  listener = null;
  assist = vi.fn().mockResolvedValue({ ok: true });
  window.gb = {
    ...window.gb,
    docs: { ...window.gb.docs, assist, assistStop: vi.fn().mockResolvedValue({ ok: true }) },
    on: ((channel: string, l: (p: Payload) => void) => {
      if (channel === 'docs:event') listener = l;
      return () => undefined;
    }) as typeof window.gb.on,
  };
});

describe('GuardedNoteEditor + inline ai', () => {
  it('an accepted suggestion is saved once, as the assistant, on the current etag', async () => {
    const send = vi.fn().mockResolvedValue({ etag: 'e2' });
    const guardRef = { current: null } as React.MutableRefObject<GuardHandle | null>;
    let editor!: Editor;
    render(
      <GuardedNoteEditor
        initialBody="alpha beta"
        initialEtag="e1"
        send={send}
        fetchLatest={vi.fn()}
        guardRef={guardRef}
        editorProps={{
          jotId: 'j1',
          debounceMs: 60_000,
          onEditorReady: (e) => {
            editor = e;
          },
          inlineAssist: {
            target: { jot_id: 'j1' },
            onAccept: () => guardRef.current?.attributeNext('assistant'),
          },
        }}
      />,
    );
    const from = textPos(editor, 'beta');
    act(() => {
      editor.commands.setTextSelection({ from, to: from + 4 });
    });
    fireEvent.keyDown(editor.view.dom, { key: 'j', ...(isMac ? { metaKey: true } : { ctrlKey: true }) });
    fireEvent.click(await screen.findByRole('button', { name: 'polish' }));
    const key = (assist.mock.calls[0]![0] as DocsAssistRequest).stream_id!;
    act(() => listener?.({ key, jotId: key, event: { type: 'done', text: 'BETA' } }));
    fireEvent.click(screen.getByRole('button', { name: /accept/ }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    const [body, ifMatch, actor] = send.mock.calls[0]!;
    expect((body as string).trim()).toBe('alpha BETA');
    expect(ifMatch).toBe('e1');
    expect(actor).toBe('assistant');
  });

  it('page mode: the handle forwards startInlineAssist and accept never touches the title (A7)', async () => {
    const send = vi.fn().mockResolvedValue({ etag: 'e2' });
    const guardRef = { current: null } as React.MutableRefObject<GuardHandle | null>;
    const handleRef = { current: null } as React.MutableRefObject<EditorHandle | null>;
    let editor!: Editor;
    render(
      <GuardedNoteEditor
        initialBody={'# Plan\n\nalpha beta'}
        initialEtag="e1"
        send={send}
        fetchLatest={vi.fn()}
        guardRef={guardRef}
        page={{ titleRule: 'note', fallbackTitle: '', breadcrumb: ['work'] }}
        editorProps={{
          jotId: 'n.md',
          debounceMs: 60_000,
          handleRef,
          onEditorReady: (e) => {
            editor = e;
          },
          inlineAssist: {
            target: { path: 'n.md' },
            onAccept: () => guardRef.current?.attributeNext('assistant'),
          },
        }}
      />,
    );
    await waitFor(() => expect(handleRef.current).not.toBeNull());
    const from = textPos(editor, 'beta');
    act(() => {
      editor.commands.setTextSelection({ from, to: from + 4 });
    });
    let started = false;
    act(() => {
      started = handleRef.current!.startInlineAssist!({ mode: 'polish' });
    });
    expect(started).toBe(true);
    const req = assist.mock.calls[0]![0] as DocsAssistRequest;
    expect(req.selection).toBe('beta');
    act(() => listener?.({ key: req.stream_id!, jotId: req.stream_id!, event: { type: 'done', text: 'BETA' } }));
    fireEvent.click(screen.getByRole('button', { name: /accept/ }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    const [body, ifMatch, actor] = send.mock.calls[0]!;
    expect((body as string).trim()).toBe('# Plan\n\nalpha BETA');
    expect(ifMatch).toBe('e1');
    expect(actor).toBe('assistant');
    expect(screen.getByLabelText('page title')).toHaveValue('Plan');
  });
});
