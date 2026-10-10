import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent } from '@testing-library/react';

const { renderMermaid } = vi.hoisted(() => ({ renderMermaid: vi.fn() }));
vi.mock('../lib/editor/mermaid-render', () => ({ renderMermaid }));

import { onGb } from '../lib/editor/events';
import { makeEditor, markdownOf } from './helpers/editor';
import { MALICIOUS_SVG, expectNoLinksOrHandlers } from './helpers/malicious-svg';

const SRC = '```mermaid\nflowchart TD\n  A --> B\n```';

describe('mermaid code block view', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    renderMermaid.mockReset();
    renderMermaid.mockResolvedValue({ ok: true, svg: '<svg data-testid="diagram"></svg>' });
  });
  afterEach(() => vi.useRealTimers());

  it('renders the SVG preview and keeps markdown unchanged', async () => {
    const editor = makeEditor(SRC);
    await act(async () => { await vi.runAllTimersAsync(); });
    expect(editor.view.dom.querySelector('.gb-mermaid-preview svg')).not.toBeNull();
    expect(renderMermaid).toHaveBeenCalledWith('flowchart TD\n  A --> B');
    expect(markdownOf(editor)).toBe(SRC);
    editor.destroy();
  });

  it('shows the error box with message and source on a render error', async () => {
    renderMermaid.mockResolvedValue({ ok: false, error: 'Parse error on line 1' });
    const editor = makeEditor('```mermaid\nnot a diagram\n```');
    await act(async () => { await vi.runAllTimersAsync(); });
    const err = editor.view.dom.querySelector('.gb-mermaid-error')!;
    expect(err.textContent).toContain('Parse error on line 1');
    expect(err.textContent).toContain('not a diagram');
    editor.destroy();
  });

  it('only the latest edit renders (debounced, stale results dropped)', async () => {
    let resolveFirst: (v: unknown) => void = () => {};
    renderMermaid
      .mockImplementationOnce(() => new Promise((r) => { resolveFirst = r; }))
      .mockResolvedValue({ ok: true, svg: '<svg data-v="new"></svg>' });
    const editor = makeEditor(SRC);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); }); // first render in flight
    act(() => {
      // insertText, not insertContent: tiptap-markdown would parse a string
      // argument as markdown and split the code block.
      const end = editor.state.doc.content.size - 1; // end of the code text
      editor.view.dispatch(editor.state.tr.insertText('X', end));
      editor.view.dispatch(editor.state.tr.insertText('Y', end + 1));
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    resolveFirst({ ok: true, svg: '<svg data-v="old"></svg>' });
    await act(async () => { await vi.runAllTimersAsync(); });
    expect(renderMermaid).toHaveBeenCalledTimes(2);
    expect(editor.view.dom.querySelector('.gb-mermaid-preview svg')?.getAttribute('data-v')).toBe('new');
    editor.destroy();
  });

  it('toggle button shows and hides the source', () => {
    const editor = makeEditor(SRC);
    const wrap = editor.view.dom.querySelector<HTMLElement>('.gb-mermaid')!;
    expect(wrap.dataset.editing).toBe('false');
    fireEvent.click(wrap.querySelector('[aria-label="toggle diagram source"]')!);
    expect(wrap.dataset.editing).toBe('true');
    editor.destroy();
  });

  it('full-screen button emits gb:diagram:open with the source', () => {
    const editor = makeEditor(SRC);
    const spy = vi.fn();
    onGb(editor, 'gb:diagram:open', spy);
    fireEvent.click(editor.view.dom.querySelector('[aria-label="open diagram full screen"]')!);
    expect(spy).toHaveBeenCalledWith({ source: 'flowchart TD\n  A --> B' });
    editor.destroy();
  });

  it('non-mermaid code blocks render as plain pre/code', () => {
    const editor = makeEditor('```python\nx = 1\n```');
    expect(editor.view.dom.querySelector('.gb-mermaid')).toBeNull();
    expect(editor.view.dom.querySelector('pre > code.language-python')?.textContent).toBe('x = 1');
    expect(renderMermaid).not.toHaveBeenCalled();
    editor.destroy();
  });

  it('strips links and handlers from the rendered SVG preview', async () => {
    renderMermaid.mockResolvedValue({ ok: true, svg: MALICIOUS_SVG });
    const editor = makeEditor(
      '```mermaid\nflowchart TD\n  A["[docs](https://evil.example/md)"] --> B\n  click A "https://evil.example/click" _blank\n```',
    );
    await act(async () => { await vi.runAllTimersAsync(); });
    const preview = editor.view.dom.querySelector('.gb-mermaid-preview')!;
    expect(preview.querySelector('[data-testid="evil-svg"]')?.namespaceURI).toBe('http://www.w3.org/2000/svg');
    expect(preview.querySelector('foreignObject')?.namespaceURI).toBe('http://www.w3.org/2000/svg');
    expect(preview.querySelector('script')).toBeNull();
    expect(preview.textContent).toContain('link in label');
    expectNoLinksOrHandlers(preview);
    editor.destroy();
  });
});
