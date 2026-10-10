import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import type { VaultQueryResponse, VaultQueryRow } from '../../shared/api-types';

const { runVaultQuery, setNoteStatus } = vi.hoisted(() => ({ runVaultQuery: vi.fn(), setNoteStatus: vi.fn() }));
vi.mock('../lib/editor/query-api', () => ({ runVaultQuery, setNoteStatus }));

import { onGb } from '../lib/editor/events';
import { QUERY_EDIT_DEBOUNCE_MS, QUERY_INDEX_RETRY_MS, QUERY_POLL_MS } from '../lib/editor/query-view';
import { makeEditor, markdownOf } from './helpers/editor';

const SRC = '```query\ntype: action_item\nstatus: open\n```';
const ROWS: VaultQueryRow[] = [
  {
    path: '20-contexts/work/a.md',
    title: 'Send Alex the budget',
    context: 'work',
    status: null,
    created: '2026-10-08T09:00:00+00:00',
    snippet: 'Alex to review the numbers',
    etag: 'aaaaaaaaaaaaaaaa',
  },
  {
    path: '20-contexts/work/b.md',
    title: 'Book the room',
    context: 'work',
    status: 'done',
    created: '2026-10-07',
    snippet: '',
    etag: 'bbbbbbbbbbbbbbbb',
  },
];

function ok(results: VaultQueryRow[] = ROWS, extra: Partial<VaultQueryResponse> = {}): VaultQueryResponse {
  return { results, diagnostics: [], indexing: false, partial: false, ...extra };
}

async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function q<T extends Element = HTMLElement>(editor: Editor, selector: string): T | null {
  return editor.view.dom.querySelector<T>(selector);
}

function menuItem(editor: Editor, label: string): HTMLButtonElement {
  const items = Array.from(editor.view.dom.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'));
  const found = items.find((b) => b.textContent === label);
  if (!found) throw new Error(`menu item not found: ${label}`);
  return found;
}

describe('query block view', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    runVaultQuery.mockReset();
    setNoteStatus.mockReset();
    runVaultQuery.mockResolvedValue(ok());
  });
  afterEach(() => vi.useRealTimers());

  it('renders live rows and keeps the markdown unchanged', async () => {
    const editor = makeEditor(SRC);
    await flush();
    expect(runVaultQuery).toHaveBeenCalledWith('type: action_item\nstatus: open');
    const rows = editor.view.dom.querySelectorAll('li.gb-query-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]!.querySelector('.gb-query-link')!.textContent).toBe('Send Alex the budget');
    expect(rows[0]!.querySelector('.gb-query-meta')!.textContent).toBe('work · 2026-10-08');
    expect(rows[0]!.querySelector('.gb-query-snippet')!.textContent).toBe('Alex to review the numbers');
    expect(rows[1]!.querySelector('.gb-query-snippet')).toBeNull();
    const boxes = editor.view.dom.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');
    expect([boxes[0]!.checked, boxes[1]!.checked]).toEqual([false, true]);
    expect(boxes[0]!.getAttribute('aria-label')).toBe('mark Send Alex the budget done');
    expect(boxes[1]!.getAttribute('aria-label')).toBe('mark Book the room open');
    expect(q(editor, '.gb-query')!.dataset.editing).toBe('false');
    expect(markdownOf(editor)).toBe(SRC);
    editor.destroy();
  });

  it('clicking a title emits gb:query:open with the path', async () => {
    const editor = makeEditor(SRC);
    await flush();
    const spy = vi.fn();
    onGb(editor, 'gb:query:open', spy);
    fireEvent.click(q(editor, '.gb-query-link')!);
    expect(spy).toHaveBeenCalledWith({ path: '20-contexts/work/a.md' });
    editor.destroy();
  });

  it('shows no matching notes for an empty result', async () => {
    runVaultQuery.mockResolvedValue(ok([]));
    const editor = makeEditor(SRC);
    await flush();
    expect(q(editor, '.gb-query-status')!.textContent).toBe('no matching notes');
    editor.destroy();
  });

  it('shows query errors inline with the source, and no list', async () => {
    runVaultQuery.mockResolvedValue(
      ok([], {
        diagnostics: [{ line: 2, col: 1, severity: 'error', message: 'unknown key `owner`', code: 'unknown-key' }],
      }),
    );
    const editor = makeEditor('```query\ntype: action_item\nowner: alex\n```');
    await flush();
    const box = q(editor, '.gb-query-error')!;
    expect(box.getAttribute('role')).toBe('alert');
    expect(box.textContent).toContain('line 2: unknown key `owner`');
    expect(box.querySelector('pre')!.textContent).toBe('type: action_item\nowner: alex');
    expect(q(editor, '.gb-query-list')).toBeNull();
    editor.destroy();
  });

  it('shows warnings above the rows and the partial notice below', async () => {
    runVaultQuery.mockResolvedValue(
      ok(ROWS, {
        partial: true,
        diagnostics: [{ line: 3, col: 8, severity: 'warning', message: 'limit capped at 100', code: 'limit-capped' }],
      }),
    );
    const editor = makeEditor(SRC);
    await flush();
    expect(q(editor, '.gb-query-warning')!.textContent).toBe('limit capped at 100');
    expect(editor.view.dom.querySelectorAll('li.gb-query-row')).toHaveLength(2);
    expect(editor.view.dom.textContent).toContain('showing the first matches only — narrow the query');
    editor.destroy();
  });

  it('shows the retry chip when the sidecar fails, and retries on click', async () => {
    runVaultQuery.mockRejectedValueOnce(new Error('sidecar down'));
    const editor = makeEditor(SRC);
    await flush();
    const chip = q<HTMLButtonElement>(editor, '.gb-query-chip')!;
    expect(chip.textContent).toBe('results unavailable — retry');
    fireEvent.click(chip);
    await flush();
    expect(runVaultQuery).toHaveBeenCalledTimes(2);
    expect(editor.view.dom.querySelectorAll('li.gb-query-row')).toHaveLength(2);
    editor.destroy();
  });

  it('treats a malformed response as unavailable', async () => {
    runVaultQuery.mockResolvedValue(null);
    const editor = makeEditor(SRC);
    await flush();
    expect(q(editor, '.gb-query-chip')).not.toBeNull();
    editor.destroy();
  });

  it('retries automatically while the index is building', async () => {
    runVaultQuery.mockResolvedValueOnce(ok([], { indexing: true }));
    const editor = makeEditor(SRC);
    await flush();
    expect(q(editor, '.gb-query-chip')).not.toBeNull();
    await flush(QUERY_INDEX_RETRY_MS);
    expect(runVaultQuery).toHaveBeenCalledTimes(2);
    expect(editor.view.dom.querySelectorAll('li.gb-query-row')).toHaveLength(2);
    editor.destroy();
  });

  it('refreshes every 60 s, on window focus and on the refresh button; stops after destroy', async () => {
    const editor = makeEditor(SRC);
    await flush();
    expect(runVaultQuery).toHaveBeenCalledTimes(1);
    await flush(QUERY_POLL_MS);
    expect(runVaultQuery).toHaveBeenCalledTimes(2);
    window.dispatchEvent(new Event('focus'));
    await flush();
    expect(runVaultQuery).toHaveBeenCalledTimes(3);
    fireEvent.click(q(editor, '[aria-label="refresh query"]')!);
    await flush();
    expect(runVaultQuery).toHaveBeenCalledTimes(4);
    editor.destroy();
    await flush(QUERY_POLL_MS * 2);
    window.dispatchEvent(new Event('focus'));
    await flush();
    expect(runVaultQuery).toHaveBeenCalledTimes(4);
  });

  it('edit query toggles the source and re-runs after typing stops', async () => {
    const editor = makeEditor(SRC);
    await flush();
    fireEvent.click(q(editor, '[aria-label="query options"]')!);
    expect(q(editor, '[role="menu"]')!.hidden).toBe(false);
    fireEvent.click(menuItem(editor, 'edit query'));
    expect(q(editor, '.gb-query')!.dataset.editing).toBe('true');
    expect(q(editor, '[role="menu"]')!.hidden).toBe(true);
    act(() => {
      const end = editor.state.doc.content.size - 1; // end of the code text
      // insertText, not insertContent: tiptap-markdown would parse a string as markdown.
      editor.view.dispatch(editor.state.tr.insertText('\nlimit: 5', end));
    });
    await flush(QUERY_EDIT_DEBOUNCE_MS - 1);
    expect(runVaultQuery).toHaveBeenCalledTimes(1);
    await flush(1);
    expect(runVaultQuery).toHaveBeenLastCalledWith('type: action_item\nstatus: open\nlimit: 5');
    fireEvent.click(q(editor, '[aria-label="query options"]')!);
    expect(menuItem(editor, 'done editing')).toBeDefined();
    editor.destroy();
  });

  it('a new empty block starts in edit mode', async () => {
    runVaultQuery.mockResolvedValue(ok([]));
    const editor = makeEditor('```query\n```');
    expect(q(editor, '.gb-query')!.dataset.editing).toBe('true');
    editor.destroy();
  });

  it('only the latest response is painted', async () => {
    let resolveFirst: (v: VaultQueryResponse) => void = () => {};
    runVaultQuery
      .mockImplementationOnce(() => new Promise((r) => { resolveFirst = r; }))
      .mockResolvedValue(ok([ROWS[1]!]));
    const editor = makeEditor(SRC);
    await flush(); // first request in flight
    fireEvent.click(q(editor, '[aria-label="refresh query"]')!);
    await flush();
    resolveFirst(ok());
    await flush();
    const titles = Array.from(editor.view.dom.querySelectorAll('.gb-query-link')).map((n) => n.textContent);
    expect(titles).toEqual(['Book the room']);
    editor.destroy();
  });

  it('an editor destroyed at once (the parse probe) sends no request', async () => {
    makeEditor(SRC).destroy();
    await flush(QUERY_POLL_MS);
    expect(runVaultQuery).not.toHaveBeenCalled();
  });

  it('other code blocks keep their own views', () => {
    const editor = makeEditor('```python\nx = 1\n```');
    expect(q(editor, '.gb-query')).toBeNull();
    expect(q(editor, 'pre > code.language-python')!.textContent).toBe('x = 1');
    editor.destroy();
  });
});
