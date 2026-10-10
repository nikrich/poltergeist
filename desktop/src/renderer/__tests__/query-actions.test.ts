import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, fireEvent } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import type { VaultQueryResponse, VaultQueryRow } from '../../shared/api-types';

const { runVaultQuery, setNoteStatus } = vi.hoisted(() => ({ runVaultQuery: vi.fn(), setNoteStatus: vi.fn() }));
vi.mock('../lib/editor/query-api', () => ({ runVaultQuery, setNoteStatus }));

import { ApiError } from '../lib/api/client';
import { makeEditor, markdownOf } from './helpers/editor';

const SRC = '```query\ntype: action_item\n```';
const OPEN: VaultQueryRow = {
  path: '20-contexts/work/a.md',
  title: 'Send Alex the budget',
  context: 'work',
  status: null,
  created: '2026-10-08',
  snippet: '',
  etag: 'aaaaaaaaaaaaaaaa',
};
const DONE: VaultQueryRow = { ...OPEN, path: '20-contexts/work/b.md', title: 'Book the room', status: 'done', etag: 'bbbbbbbbbbbbbbbb' };

function ok(results: VaultQueryRow[] = [OPEN, DONE], extra: Partial<VaultQueryResponse> = {}): VaultQueryResponse {
  return { results, diagnostics: [], indexing: false, partial: false, ...extra };
}

async function flush(ms = 0): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function boxes(editor: Editor): HTMLInputElement[] {
  return Array.from(editor.view.dom.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
}

function freezeItem(editor: Editor): HTMLButtonElement {
  fireEvent.click(editor.view.dom.querySelector('[aria-label="query options"]')!);
  const items = Array.from(editor.view.dom.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'));
  return items.find((b) => b.textContent === 'freeze')!;
}

describe('query block actions', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    runVaultQuery.mockReset();
    setNoteStatus.mockReset();
    runVaultQuery.mockResolvedValue(ok());
    setNoteStatus.mockResolvedValue({ path: OPEN.path, status: 'done', etag: 'cccccccccccccccc' });
  });
  afterEach(() => vi.useRealTimers());

  it('ticking an open row marks it done with its etag, then refreshes', async () => {
    const editor = makeEditor(SRC);
    await flush();
    runVaultQuery.mockResolvedValue(ok([DONE]));
    fireEvent.click(boxes(editor)[0]!);
    await flush();
    expect(setNoteStatus).toHaveBeenCalledWith('20-contexts/work/a.md', 'done', 'aaaaaaaaaaaaaaaa');
    expect(runVaultQuery).toHaveBeenCalledTimes(2);
    expect(boxes(editor)).toHaveLength(1);
    expect(editor.view.dom.querySelector('.gb-query-notice')).toBeNull();
    editor.destroy();
  });

  it('unticking a done row writes status open', async () => {
    const editor = makeEditor(SRC);
    await flush();
    fireEvent.click(boxes(editor)[1]!);
    await flush();
    expect(setNoteStatus).toHaveBeenCalledWith('20-contexts/work/b.md', 'open', 'bbbbbbbbbbbbbbbb');
    editor.destroy();
  });

  it('a 409 shows the changed-elsewhere notice and refreshes', async () => {
    setNoteStatus.mockRejectedValue(new ApiError('note changed since you read it', 409));
    const editor = makeEditor(SRC);
    await flush();
    fireEvent.click(boxes(editor)[0]!);
    await flush();
    expect(runVaultQuery).toHaveBeenCalledTimes(2);
    const notice = editor.view.dom.querySelector('.gb-query-notice')!;
    expect(notice.getAttribute('role')).toBe('status');
    expect(notice.textContent).toBe('Send Alex the budget changed elsewhere — list refreshed, try again');
    editor.destroy();
  });

  it('other failures say what went wrong', async () => {
    setNoteStatus.mockRejectedValue(new ApiError('Note not found: a.md', 404));
    const editor = makeEditor(SRC);
    await flush();
    fireEvent.click(boxes(editor)[0]!);
    await flush();
    expect(editor.view.dom.querySelector('.gb-query-notice')!.textContent).toBe(
      'could not update Send Alex the budget: Note not found: a.md',
    );
    editor.destroy();
  });

  it('a row is disabled while its write is in flight', async () => {
    let finish: () => void = () => {};
    setNoteStatus.mockImplementation(() => new Promise<void>((r) => { finish = r; }));
    const editor = makeEditor(SRC);
    await flush();
    fireEvent.click(boxes(editor)[0]!);
    expect(boxes(editor)[0]!.disabled).toBe(true);
    fireEvent.click(boxes(editor)[0]!);
    expect(setNoteStatus).toHaveBeenCalledTimes(1);
    finish();
    await flush();
    editor.destroy();
  });

  it('freeze replaces the block with a static task list', async () => {
    const editor = makeEditor(`${SRC}\n\nafter`);
    await flush();
    const item = freezeItem(editor);
    expect(item.disabled).toBe(false);
    fireEvent.click(item);
    expect(markdownOf(editor)).toBe(
      '- [ ] [[20-contexts/work/a|Send Alex the budget]]\n- [x] [[20-contexts/work/b|Book the room]]\n\nafter',
    );
    expect(editor.view.dom.querySelector('.gb-query')).toBeNull();
    editor.destroy();
  });

  it('freezing zero rows leaves a plain sentence', async () => {
    runVaultQuery.mockResolvedValue(ok([]));
    const editor = makeEditor(SRC);
    await flush();
    fireEvent.click(freezeItem(editor));
    expect(markdownOf(editor)).toBe('no matching notes');
    editor.destroy();
  });

  it('freeze is disabled while the query has errors or has not loaded', async () => {
    let resolve: (v: VaultQueryResponse) => void = () => {};
    runVaultQuery.mockImplementationOnce(() => new Promise((r) => { resolve = r; }));
    const editor = makeEditor(SRC);
    await flush();
    expect(freezeItem(editor).disabled).toBe(true);
    resolve(ok([], { diagnostics: [{ line: 1, col: 1, severity: 'error', message: 'bad', code: 'bad-value' }] }));
    await flush();
    expect(freezeItem(editor).disabled).toBe(true);
    editor.destroy();
  });

  it('a read-only editor disables ticking and freeze', async () => {
    const editor = makeEditor(SRC, false);
    await flush();
    expect(boxes(editor).every((b) => b.disabled)).toBe(true);
    fireEvent.click(boxes(editor)[0]!);
    await flush();
    expect(setNoteStatus).not.toHaveBeenCalled();
    expect(freezeItem(editor).disabled).toBe(true);
    editor.destroy();
  });
});
