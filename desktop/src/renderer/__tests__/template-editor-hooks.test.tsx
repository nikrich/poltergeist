import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { useCreateFromTemplate } from '../lib/api/hooks';
import {
  lintTemplate,
  saveTemplateSource,
  useCreateBlankTemplate,
  useTemplateDryRun,
  useTemplateSource,
} from '../lib/api/template-editor';
import {
  LAST_ANSWERS_KEY,
  MAX_REMEMBERED_TEMPLATES,
  initialAnswers,
  rememberAnswers,
} from '../lib/templates/last-answers';
import { stubBrokenLocalStorage, stubLocalStorage } from './helpers/memory-storage';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);
const patchMock = vi.mocked(client.patch);

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  stubLocalStorage();
});
afterEach(() => {
  vi.unstubAllGlobals();
  getMock.mockReset();
  postMock.mockReset();
  patchMock.mockReset();
});

describe('template editor calls', () => {
  it('reads source by encoded id only when an id is given', async () => {
    getMock.mockResolvedValue({ id: 'one-on-one', path: 'p', source: 's', etag: 'e' });
    renderHook(() => useTemplateSource(null), { wrapper });
    expect(getMock).not.toHaveBeenCalled();
    const { result } = renderHook(() => useTemplateSource('one-on-one'), { wrapper });
    await waitFor(() => expect(result.current.data?.etag).toBe('e'));
    expect(getMock).toHaveBeenCalledWith('/v1/templates/one-on-one/source');
  });

  it('saves with If-Match, or without it to overwrite', async () => {
    patchMock.mockResolvedValue({ id: 'x', path: 'p', etag: 'e2', status: 'applied', changeId: null });
    await saveTemplateSource('x', 'src', 'e1');
    expect(patchMock).toHaveBeenLastCalledWith('/v1/templates/x/source', { source: 'src' }, { ifMatch: 'e1' });
    await saveTemplateSource('x', 'src', null);
    expect(patchMock).toHaveBeenLastCalledWith('/v1/templates/x/source', { source: 'src' }, { ifMatch: null });
  });

  it('lints and test-runs through the sidecar', async () => {
    postMock.mockResolvedValueOnce({ diagnostics: [{ line: 1, col: 1, severity: 'error', message: 'm', code: 'c' }] });
    expect(await lintTemplate('src')).toHaveLength(1);
    expect(postMock).toHaveBeenLastCalledWith('/v1/templates/lint', { source: 'src' });

    postMock.mockResolvedValueOnce({ ok: true });
    const { result } = renderHook(() => useTemplateDryRun(), { wrapper });
    await result.current.mutateAsync({ source: 's', answers: { a: 'b' }, id: 'x' });
    expect(postMock).toHaveBeenLastCalledWith('/v1/templates/render', {
      source: 's',
      answers: { a: 'b' },
      id: 'x',
      dry_run: true,
    });
  });

  it('creates a blank template by name', async () => {
    postMock.mockResolvedValue({ id: 'weekly', path: 'p', etag: 'e', status: 'applied', changeId: null });
    const { result } = renderHook(() => useCreateBlankTemplate(), { wrapper });
    await result.current.mutateAsync('Weekly');
    expect(postMock).toHaveBeenCalledWith('/v1/templates', { name: 'Weekly' });
  });

  it('remembers the answers of a successful create', async () => {
    postMock.mockResolvedValue({ path: 'a.md', title: 'A', etag: 'e', status: 'applied' });
    const { result } = renderHook(() => useCreateFromTemplate(), { wrapper });
    await result.current.mutateAsync({ id: 'one-on-one', answers: { person: 'Alex', focus: '' } });
    expect(initialAnswers('one-on-one', ['person', 'focus'])).toEqual({ person: 'Alex' });
  });
});

describe('last answers', () => {
  it('falls back to the latest answer for the same prompt id in any template', () => {
    rememberAnswers('one-on-one', { person: 'Alex' });
    rememberAnswers('meeting-notes', { topic: 'Planning' });
    expect(initialAnswers('new-template', ['person', 'topic', 'other'])).toEqual({
      person: 'Alex',
      topic: 'Planning',
    });
    rememberAnswers('meeting-notes', { person: 'Robin' });
    expect(initialAnswers('one-on-one', ['person'])).toEqual({ person: 'Alex' });
    expect(initialAnswers('other', ['person'])).toEqual({ person: 'Robin' });
  });

  it('caps what it keeps and survives corrupt or blocked storage', () => {
    for (let i = 0; i < MAX_REMEMBERED_TEMPLATES + 5; i += 1) rememberAnswers(`t${i}`, { a: `v${i}` });
    const stored = JSON.parse(localStorage.getItem(LAST_ANSWERS_KEY)!);
    expect(Object.keys(stored.byTemplate)).toHaveLength(MAX_REMEMBERED_TEMPLATES);
    expect(stored.byTemplate.t0).toBeUndefined();
    rememberAnswers('long', { a: 'x'.repeat(501) });
    expect(initialAnswers('long', ['a'])).toEqual({ a: `v${MAX_REMEMBERED_TEMPLATES + 4}` });

    localStorage.setItem(LAST_ANSWERS_KEY, '{not json');
    expect(initialAnswers('x', ['a'])).toEqual({});
    stubBrokenLocalStorage();
    expect(() => rememberAnswers('x', { a: 'b' })).not.toThrow();
    expect(initialAnswers('x', ['a'])).toEqual({});
  });
});
