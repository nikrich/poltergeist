import { act, createEvent, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Editor } from '@tiptap/core';
import {
  GuardedNoteEditor,
  type GuardHandle,
  type GuardedNoteEditorProps,
  type PageChrome,
} from '../components/GuardedNoteEditor';
import type { EditorHandle } from '../components/RichMarkdownEditor';
import { ApiError } from '../lib/api/client';
import { getMarkdown } from '../lib/editor/markdown';

const E1 = 'aaaaaaaaaaaaaaaa';
const E2 = 'cccccccccccccccc';
const NOTE: PageChrome = { titleRule: 'note', fallbackTitle: '', breadcrumb: ['work', 'payments'] };

function setup(
  initialBody: string,
  page: PageChrome | undefined,
  guardRef?: React.MutableRefObject<GuardHandle | null>,
  extra: Partial<GuardedNoteEditorProps['editorProps']> = {},
) {
  const send = vi.fn().mockResolvedValue({ etag: E2 });
  const fetchLatest = vi.fn().mockResolvedValue({ body: initialBody, etag: E1 });
  let editor: Editor | undefined;
  render(
    <GuardedNoteEditor
      initialBody={initialBody}
      initialEtag={E1}
      send={send}
      fetchLatest={fetchLatest}
      guardRef={guardRef}
      page={page}
      editorProps={{
        jotId: 'n.md',
        debounceMs: 10,
        onEditorReady: (e) => {
          editor = e;
        },
        ...extra,
      }}
    />,
  );
  return { send, getEditor: () => editor };
}

const title = () => screen.getByLabelText('page title') as HTMLTextAreaElement;
const settle = () => new Promise((r) => setTimeout(r, 60));

describe('GuardedNoteEditor page mode (A7)', () => {
  it('shows the leading H1 as the title, the breadcrumb, and only the rest in the editor', async () => {
    const { getEditor } = setup('# Plan\n\nbody text', NOTE);
    expect(title()).toHaveValue('Plan');
    const crumbs = screen.getByRole('navigation', { name: 'breadcrumb' });
    expect(within(crumbs).getByText('work')).toBeInTheDocument();
    expect(within(crumbs).getByText('payments')).toBeInTheDocument();
    await waitFor(() => expect(getEditor()).toBeDefined());
    expect(getMarkdown(getEditor()!).trim()).toBe('body text');
  });

  it('a body edit saves the untouched title line in front of it', async () => {
    const { send, getEditor } = setup('# Plan\n\nbody text', NOTE);
    await waitFor(() => expect(getEditor()).toBeDefined());
    act(() => {
      const ed = getEditor()!;
      ed.commands.insertContentAt(ed.state.doc.content.size, 'my tail');
    });
    await waitFor(() => expect(send).toHaveBeenCalled());
    const body = send.mock.calls.at(-1)![0] as string;
    expect(body.startsWith('# Plan\n\nbody text')).toBe(true);
    expect(body).toContain('my tail');
  });

  it('renaming on blur saves the new H1 with the body unchanged', async () => {
    const { send } = setup('# Plan\n\nbody text', NOTE);
    fireEvent.change(title(), { target: { value: 'Launch plan' } });
    fireEvent.blur(title());
    await waitFor(() => expect(send).toHaveBeenCalledWith('# Launch plan\n\nbody text', E1));
  });

  it('typing in the title saves after the debounce without leaving the field', async () => {
    const { send } = setup('# Plan\n\nbody text', NOTE);
    fireEvent.change(title(), { target: { value: 'Launch' } });
    await waitFor(() => expect(send).toHaveBeenCalledWith('# Launch\n\nbody text', E1));
  });

  it('Enter saves the title and does not add a line break', async () => {
    const { send } = setup('# Plan\n\nbody text', NOTE);
    fireEvent.change(title(), { target: { value: 'Launch plan' } });
    const enter = createEvent.keyDown(title(), { key: 'Enter' });
    fireEvent(title(), enter);
    expect(enter.defaultPrevented).toBe(true);
    await waitFor(() => expect(send).toHaveBeenCalledWith('# Launch plan\n\nbody text', E1));
  });

  it('an unchanged or emptied title saves nothing, and an empty one reverts on blur', async () => {
    const { send } = setup('# Plan\n\nbody text', NOTE);
    fireEvent.blur(title());
    fireEvent.change(title(), { target: { value: '   ' } });
    fireEvent.blur(title());
    expect(title()).toHaveValue('Plan');
    await settle();
    expect(send).not.toHaveBeenCalled();
  });

  it('on blur the field shows exactly what was saved (collapsed whitespace, 200-char cap)', async () => {
    const { send } = setup('# Plan\n\nbody text', NOTE);
    fireEvent.change(title(), { target: { value: '  Launch   plan  ' } });
    fireEvent.blur(title());
    expect(title()).toHaveValue('Launch plan');
    await waitFor(() => expect(send).toHaveBeenCalledWith('# Launch plan\n\nbody text', E1));

    fireEvent.change(title(), { target: { value: 'y'.repeat(250) } });
    fireEvent.blur(title());
    expect(title()).toHaveValue('y'.repeat(200));
    await waitFor(() =>
      expect(send).toHaveBeenLastCalledWith(`# ${'y'.repeat(200)}\n\nbody text`, E2),
    );
  });

  it('pasted line breaks become spaces', async () => {
    const { send } = setup('# Plan\n\nbody text', NOTE);
    fireEvent.change(title(), { target: { value: 'Two\nlines' } });
    expect(title()).toHaveValue('Two lines');
    fireEvent.blur(title());
    await waitFor(() => expect(send).toHaveBeenCalledWith('# Two lines\n\nbody text', E1));
  });

  it('Esc with an unsaved title reverts it and is consumed; Esc on a clean title is left alone', () => {
    setup('# Plan\n\nbody text', NOTE);
    fireEvent.change(title(), { target: { value: 'Draft' } });
    const dirty = createEvent.keyDown(title(), { key: 'Escape' });
    fireEvent(title(), dirty);
    expect(dirty.defaultPrevented).toBe(true);
    expect(title()).toHaveValue('Plan');
    const clean = createEvent.keyDown(title(), { key: 'Escape' });
    fireEvent(title(), clean);
    expect(clean.defaultPrevented).toBe(false);
  });

  it('a jot keeps its plain first-line title plain', async () => {
    const { send } = setup('first jot\n\nfull body here', { titleRule: 'jot', fallbackTitle: '', breadcrumb: [] });
    expect(title()).toHaveValue('first jot');
    expect(screen.queryByRole('navigation', { name: 'breadcrumb' })).toBeNull();
    fireEvent.change(title(), { target: { value: 'Sprint retro' } });
    fireEvent.blur(title());
    await waitFor(() => expect(send).toHaveBeenCalledWith('Sprint retro\n\nfull body here', E1));
  });

  it('a note without an H1 shows its fallback title and only writes an H1 when renamed', async () => {
    const { send } = setup('hand-written', { titleRule: 'note', fallbackTitle: 'Spec', breadcrumb: [] });
    expect(title()).toHaveValue('Spec');
    fireEvent.blur(title());
    await settle();
    expect(send).not.toHaveBeenCalled();
    fireEvent.change(title(), { target: { value: 'Spec v2' } });
    fireEvent.blur(title());
    await waitFor(() => expect(send).toHaveBeenCalledWith('# Spec v2\n\nhand-written', E1));
  });

  it('a body with no title and no fallback shows the Untitled placeholder', () => {
    setup('line one\nline two', { titleRule: 'jot', fallbackTitle: '', breadcrumb: [] });
    expect(title()).toHaveValue('');
    expect(title()).toHaveAttribute('placeholder', 'Untitled');
  });

  it('a title rename and body typing in the same debounce window both land', async () => {
    const { send, getEditor } = setup('# Plan\n\nbody text', NOTE);
    await waitFor(() => expect(getEditor()).toBeDefined());
    act(() => {
      const ed = getEditor()!;
      ed.commands.insertContentAt(ed.state.doc.content.size, 'my tail');
    });
    fireEvent.change(title(), { target: { value: 'Launch plan' } });
    fireEvent.blur(title());
    await waitFor(() => {
      const last = send.mock.calls.at(-1)![0] as string;
      expect(last.startsWith('# Launch plan\n\nbody text')).toBe(true);
      expect(last).toContain('my tail');
    });
  });

  it('a history restore re-reads the title from the restored body', async () => {
    const guardRef = { current: null as GuardHandle | null };
    const { getEditor } = setup('# Plan\n\nbody text', NOTE, guardRef);
    await waitFor(() => expect(guardRef.current).not.toBeNull());
    await act(async () => {
      await guardRef.current!.restore(async () => ({ body: '# Old plan\n\nold body', etag: E2 }));
    });
    expect(title()).toHaveValue('Old plan');
    await waitFor(() => expect(getMarkdown(getEditor()!).trim()).toBe('old body'));
  });

  it('keep theirs re-reads the title from their body, with no duplicated title line', async () => {
    const send = vi
      .fn()
      .mockRejectedValueOnce(new ApiError('changed', 409))
      .mockResolvedValue({ etag: 'dddddddddddddddd' });
    const fetchLatest = vi.fn().mockResolvedValue({ body: '# Their plan\n\ntheir body', etag: E2 });
    let editor: Editor | undefined;
    render(
      <GuardedNoteEditor
        initialBody={'# Plan\n\nbody text'}
        initialEtag={E1}
        send={send}
        fetchLatest={fetchLatest}
        page={NOTE}
        editorProps={{
          jotId: 'n.md',
          debounceMs: 10,
          onEditorReady: (e) => {
            editor = e;
          },
        }}
      />,
    );
    await waitFor(() => expect(editor).toBeDefined());
    act(() => {
      editor!.commands.insertContentAt(editor!.state.doc.content.size, 'my tail');
    });
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'keep theirs' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
    expect(title()).toHaveValue('Their plan');
    await waitFor(() => expect(getMarkdown(editor!).trim()).toBe('their body'));
    expect(getMarkdown(editor!)).not.toContain('Their plan');

    const sentBefore = send.mock.calls.length;
    act(() => {
      editor!.commands.insertContentAt(editor!.state.doc.content.size, 'next');
    });
    await waitFor(() => expect(send.mock.calls.length).toBeGreaterThan(sentBefore));
    const [saved, etag] = send.mock.calls.at(-1)!;
    expect((saved as string).startsWith('# Their plan\n\ntheir body')).toBe(true);
    expect((saved as string).split('\n').filter((l) => /^#\s/.test(l))).toHaveLength(1);
    expect(saved as string).not.toContain('my tail');
    expect(etag).toBe(E2);
  });

  it('reload adopts an outside write and re-splits it', async () => {
    const guardRef = { current: null as GuardHandle | null };
    const { send, getEditor } = setup('# Plan\n\nbody text', NOTE, guardRef);
    await waitFor(() => expect(guardRef.current).not.toBeNull());
    act(() => guardRef.current!.reload(E2, '# Plan\n\nbody text\n\n> photo text'));
    expect(title()).toHaveValue('Plan');
    await waitFor(() => expect(getMarkdown(getEditor()!)).toContain('photo text'));
    expect(getMarkdown(getEditor()!)).not.toContain('# Plan');
    fireEvent.change(title(), { target: { value: 'Plan B' } });
    fireEvent.blur(title());
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith('# Plan B\n\nbody text\n\n> photo text', E2),
    );
  });

  it('focus mode keeps the title but hides the breadcrumb and byline', () => {
    setup('# Plan\n\nbody text', { ...NOTE, byline: <span>byline here</span> }, undefined, { focus: true });
    expect(title()).toHaveValue('Plan');
    expect(screen.queryByRole('navigation', { name: 'breadcrumb' })).toBeNull();
    expect(screen.queryByText('byline here')).toBeNull();
  });

  it('read-only pages have a read-only title', () => {
    setup('# Plan\n\nbody text', NOTE, undefined, { readOnly: true });
    expect(title()).toHaveAttribute('readonly');
  });

  it('without page there is no title field', () => {
    setup('# Plan\n\nbody text', undefined);
    expect(screen.queryByLabelText('page title')).toBeNull();
  });
});

describe('GuardedNoteEditor page mode: the editor handle (A7 R2)', () => {
  function withHandle(body: string, guardRef?: React.MutableRefObject<GuardHandle | null>) {
    const handleRef = { current: null as EditorHandle | null };
    const out = setup(body, NOTE, guardRef, { handleRef });
    return { ...out, handleRef };
  }
  const titleLines = (s: string) => s.split('\n').filter((l) => /^#\s/.test(l)).length;

  it('getMarkdown returns the whole note, title line included', async () => {
    const { handleRef, getEditor } = withHandle('# Plan\n\nbody text');
    await waitFor(() => expect(getEditor()).toBeDefined());
    await waitFor(() => expect(handleRef.current).not.toBeNull());
    expect(handleRef.current!.getMarkdown()).toBe('# Plan\n\nbody text');
  });

  it('a whole-doc replace that owns a title moves it into the title field, never into the body', async () => {
    const { send, handleRef, getEditor } = withHandle('# Plan\n\nbody text');
    await waitFor(() => expect(handleRef.current).not.toBeNull());
    act(() => handleRef.current!.replaceWith('# New plan\n\nnew body', 'doc'));
    expect(title()).toHaveValue('New plan');
    expect(getMarkdown(getEditor()!)).not.toContain('New plan');
    await waitFor(() => expect(send).toHaveBeenCalled());
    const saved = send.mock.calls.at(-1)![0] as string;
    expect(saved.startsWith('# New plan\n\nnew body')).toBe(true);
    expect(titleLines(saved)).toBe(1);
    expect(handleRef.current!.getMarkdown().startsWith('# New plan\n\nnew body')).toBe(true);
  });

  it('a whole-doc replace without a title keeps the page title', async () => {
    const { send, handleRef } = withHandle('# Plan\n\nbody text');
    await waitFor(() => expect(handleRef.current).not.toBeNull());
    act(() => handleRef.current!.replaceWith('just a body', 'doc'));
    expect(title()).toHaveValue('Plan');
    await waitFor(() => expect(send).toHaveBeenCalled());
    const saved = send.mock.calls.at(-1)![0] as string;
    expect(saved.startsWith('# Plan\n\njust a body')).toBe(true);
    expect(titleLines(saved)).toBe(1);
  });

  it('a replace that changes only the title still saves, once, attributed to the next actor', async () => {
    const guardRef = { current: null as GuardHandle | null };
    const { send, handleRef } = withHandle('# Plan\n\nbody text', guardRef);
    await waitFor(() => expect(handleRef.current).not.toBeNull());
    await waitFor(() => expect(guardRef.current).not.toBeNull());
    act(() => {
      // DocsAssistPanel: replaceWith, then onAccept -> attributeNext, synchronously.
      handleRef.current!.replaceWith('# Better plan\n\nbody text', 'doc');
      guardRef.current!.attributeNext('assistant');
    });
    expect(send).not.toHaveBeenCalled();
    await waitFor(() => expect(send).toHaveBeenCalled());
    expect(send.mock.calls[0]![0]).toBe('# Better plan\n\nbody text');
    expect(send.mock.calls[0]![2]).toBe('assistant');
    await settle();
    expect(send).toHaveBeenCalledTimes(1);
  });

  it('an Accept that changes title and body keeps the assistant body in the assistant save, even if the user types', async () => {
    const guardRef = { current: null as GuardHandle | null };
    const { send, handleRef, getEditor } = withHandle('# Plan\n\nbody text', guardRef);
    await waitFor(() => expect(getEditor()).toBeDefined());
    await waitFor(() => expect(handleRef.current).not.toBeNull());
    await waitFor(() => expect(guardRef.current).not.toBeNull());
    act(() => {
      handleRef.current!.replaceWith('# New plan\n\nnew body', 'doc');
      guardRef.current!.attributeNext('assistant');
      // The user types before the debounce runs out: the editor's timer restarts.
      const ed = getEditor()!;
      ed.commands.insertContentAt(ed.state.doc.content.size, 'typed');
    });
    await waitFor(() => expect(send).toHaveBeenCalled());
    await settle();
    const assistant = send.mock.calls.filter((c) => c[2] === 'assistant');
    expect(assistant).toHaveLength(1);
    expect(assistant[0]![0]).toContain('new body');
    for (const [body] of send.mock.calls) {
      expect(body as string).not.toContain('body text');
      expect(titleLines(body as string)).toBe(1);
    }
  });

  it('getHTML puts the page title in front as an escaped h1', async () => {
    const { handleRef, getEditor } = withHandle('# A <b> & c\n\nbody text');
    await waitFor(() => expect(getEditor()).toBeDefined());
    await waitFor(() => expect(handleRef.current).not.toBeNull());
    const html = handleRef.current!.getHTML();
    expect(html.startsWith('<h1>A &lt;b&gt; &amp; c</h1>')).toBe(true);
    expect(html).toContain('body text');
  });

  it('selection calls pass through to the editor', async () => {
    const { handleRef, getEditor } = withHandle('# Plan\n\nbody text');
    await waitFor(() => expect(getEditor()).toBeDefined());
    await waitFor(() => expect(handleRef.current).not.toBeNull());
    expect(handleRef.current!.getSelectionMarkdown()).toBe('');
  });

  it('without page the handle is the editor\'s own (body including the title line)', async () => {
    const handleRef = { current: null as EditorHandle | null };
    setup('# Plan\n\nbody text', undefined, undefined, { handleRef });
    await waitFor(() => expect(handleRef.current).not.toBeNull());
    expect(handleRef.current!.getMarkdown()).toBe('# Plan\n\nbody text');
    expect(handleRef.current!.getHTML()).not.toMatch(/^<h1>Plan<\/h1><h1>/);
  });
});

describe('PageTitle height (A7)', () => {
  it('re-measures when its width changes, without a draft change', () => {
    let fire: (() => void) | undefined;
    const RO = vi.fn((cb: () => void) => {
      fire = cb;
      return { observe: vi.fn(), disconnect: vi.fn(), unobserve: vi.fn() };
    });
    vi.stubGlobal('ResizeObserver', RO);
    try {
      setup('# A long plan title\n\nbody text', NOTE);
      const el = title();
      let width = 600;
      let height = 40;
      Object.defineProperty(el, 'clientWidth', { configurable: true, get: () => width });
      Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => height });
      expect(fire).toBeDefined();
      width = 300;
      height = 80;
      act(() => fire!());
      expect(el.style.height).toBe('80px');
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('leaves sizing to CSS where field-sizing is supported', () => {
    const supports = vi.fn((prop: string) => prop === 'field-sizing');
    vi.stubGlobal('CSS', { supports });
    try {
      setup('# Plan\n\nbody text', NOTE);
      expect(title().style.height).toBe('');
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
