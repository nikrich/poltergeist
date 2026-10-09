import { afterEach, describe, expect, it, vi } from 'vitest';
import { Editor } from '@tiptap/core';
import * as client from '../lib/api/client';
import {
  createLatestFetcher,
  fetchSuggestions,
  isInTable,
  linkTextFor,
  notePathFromTarget,
  noteTarget,
  type SuggestResult,
} from '../lib/editor/link-suggest';
import { buildEditorExtensions } from '../lib/editor/extensions';
import type { SuggestItem } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);

const PAGE: SuggestItem = {
  kind: 'page', label: 'Alpha plan', path: '20-contexts/work/alpha-plan.md',
  context: 'work', detail: '20-contexts/work/alpha-plan', count: null,
};
const PERSON: SuggestItem = {
  kind: 'person', label: 'Alex', path: '30-cross-context/people/alex.md',
  context: '', detail: '30-cross-context/people/alex', count: null,
};
const TAG: SuggestItem = { kind: 'tag', label: 'roadmap', path: null, context: '', detail: '2 notes', count: 2 };

afterEach(() => {
  getMock.mockReset();
  vi.useRealTimers();
});

describe('fetchSuggestions', () => {
  it('calls the suggest route with kind, encoded query and limit', async () => {
    getMock.mockResolvedValue({ items: [PAGE], indexing: false });
    await expect(fetchSuggestions('page', 'alpha plan')).resolves.toEqual({ items: [PAGE], indexing: false });
    expect(getMock).toHaveBeenCalledWith('/v1/vault/suggest?kind=page&q=alpha%20plan&limit=20');
  });

  it('passes the indexing flag through', async () => {
    getMock.mockResolvedValue({ items: [], indexing: true });
    await expect(fetchSuggestions('tag', 'r')).resolves.toEqual({ items: [], indexing: true });
  });

  it('resolves empty when the request fails', async () => {
    getMock.mockRejectedValue(new Error('sidecar down'));
    await expect(fetchSuggestions('page', 'a')).resolves.toEqual({ items: [], indexing: false });
  });

  it('resolves empty after the 300 ms timeout', async () => {
    vi.useFakeTimers();
    getMock.mockReturnValue(new Promise(() => {}));
    const p = fetchSuggestions('page', 'a');
    await vi.advanceTimersByTimeAsync(300);
    await expect(p).resolves.toEqual({ items: [], indexing: false });
  });

  it('treats a malformed body as no items', async () => {
    getMock.mockResolvedValue({ nope: true });
    await expect(fetchSuggestions('page', 'a')).resolves.toEqual({ items: [], indexing: false });
  });
});

describe('createLatestFetcher', () => {
  it('answers a superseded request with the newest result', async () => {
    const resolvers: Array<(r: SuggestResult) => void> = [];
    const fetcher = vi.fn(() => new Promise<SuggestResult>((res) => resolvers.push(res)));
    const latest = createLatestFetcher(fetcher);
    const first = latest('page', 'a');
    const second = latest('page', 'al');
    resolvers[1]!({ items: [PAGE], indexing: false });
    resolvers[0]!({ items: [], indexing: false });
    await expect(first).resolves.toEqual({ items: [PAGE], indexing: false });
    await expect(second).resolves.toEqual({ items: [PAGE], indexing: false });
  });

  it('re-checks for a newer request after awaiting a superseding one', async () => {
    const resolvers: Array<(r: SuggestResult) => void> = [];
    const fetcher = vi.fn(() => new Promise<SuggestResult>((res) => resolvers.push(res)));
    const latest = createLatestFetcher(fetcher);
    const resultA: SuggestResult = { items: [], indexing: false };
    const resultB: SuggestResult = { items: [TAG], indexing: false };
    const resultC: SuggestResult = { items: [PERSON], indexing: false };
    const applied: string[] = [];
    const label = (r: SuggestResult) => (r === resultA ? 'A' : r === resultB ? 'B' : r === resultC ? 'C' : '?');
    const a = latest('page', 'a').then((r) => (applied.push(`a:${label(r)}`), r));
    const b = latest('page', 'al').then((r) => (applied.push(`b:${label(r)}`), r));
    resolvers[0]!(resultA);
    await Promise.resolve();
    await Promise.resolve();
    const c = latest('page', 'alp').then((r) => (applied.push(`c:${label(r)}`), r));
    resolvers[2]!(resultC);
    resolvers[1]!(resultB);
    await expect(a).resolves.toBe(resultC);
    await expect(b).resolves.toBe(resultC);
    await expect(c).resolves.toBe(resultC);
    expect(applied.every((s) => s.endsWith(':C'))).toBe(true);
  });
});

describe('insertion text', () => {
  it('builds the spec markdown forms', () => {
    expect(linkTextFor(PAGE, { inTable: false })).toBe('[[20-contexts/work/alpha-plan|Alpha plan]]');
    expect(linkTextFor(PERSON, { inTable: false })).toBe('[[30-cross-context/people/alex|@Alex]]');
    expect(linkTextFor(TAG, { inTable: false })).toBe('#roadmap');
  });

  it('drops the alias inside tables', () => {
    expect(linkTextFor(PAGE, { inTable: true })).toBe('[[20-contexts/work/alpha-plan]]');
    expect(linkTextFor(PERSON, { inTable: true })).toBe('[[30-cross-context/people/alex]]');
  });

  it('strips characters that would break the wikilink from the alias', () => {
    const odd = { ...PAGE, label: 'Plan [v2] | draft' };
    expect(linkTextFor(odd, { inTable: false })).toBe('[[20-contexts/work/alpha-plan|Plan v2 draft]]');
  });

  it('maps paths and targets', () => {
    expect(noteTarget('20-contexts/work/a.md')).toBe('20-contexts/work/a');
    expect(notePathFromTarget('20-contexts/work/a')).toBe('20-contexts/work/a.md');
    expect(notePathFromTarget('20-contexts/work/a.md')).toBe('20-contexts/work/a.md');
    expect(notePathFromTarget(' 20-contexts/work/a#Heading ')).toBe('20-contexts/work/a.md');
  });
});

describe('isInTable', () => {
  it('detects a cursor inside a table cell', () => {
    const editor = new Editor({
      extensions: buildEditorExtensions(),
      content: 'para\n\n| a | b |\n| --- | --- |\n| x | y |',
    });
    try {
      editor.commands.setTextSelection(2);
      expect(isInTable(editor)).toBe(false);
      let cellPos = -1;
      editor.state.doc.descendants((node, pos) => {
        if (node.isText && node.text === 'x') cellPos = pos + 1;
      });
      editor.commands.setTextSelection(cellPos);
      expect(isInTable(editor)).toBe(true);
    } finally {
      editor.destroy();
    }
  });
});
