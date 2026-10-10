import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import {
  useBacklinks,
  useCreateJot,
  useDeleteJot,
  useExtractPhoto,
  useRouteJot,
  useUpdateJot,
  useUpdateNoteByPath,
} from '../lib/api/hooks';

const request = vi.fn();
beforeEach(() => {
  request.mockReset();
  window.gb = { ...window.gb, api: { request } } as typeof window.gb;
});

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('useBacklinks', () => {
  it('fetches backlinks for an encoded path', async () => {
    request.mockResolvedValue({ ok: true, data: { items: [], indexing: false } });
    const { result } = renderHook(() => useBacklinks('20-contexts/work/a b.md'), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(request).toHaveBeenCalledWith('GET', '/v1/vault/backlinks?path=20-contexts%2Fwork%2Fa%20b.md');
  });

  it('stays idle without a path', () => {
    renderHook(() => useBacklinks(null), { wrapper });
    expect(request).not.toHaveBeenCalled();
  });
});

describe('saves invalidate backlinks', () => {
  function spyClient() {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const spy = vi.spyOn(qc, 'invalidateQueries');
    const w = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    return { spy, w };
  }
  const backlinksInvalidated = (spy: ReturnType<typeof spyClient>['spy']) =>
    spy.mock.calls.some(([f]) => JSON.stringify(f?.queryKey) === '["vault","backlinks"]');

  it('after a note-body save', async () => {
    request.mockResolvedValue({ ok: true, data: { path: 'a.md', updated: null } });
    const { spy, w } = spyClient();
    const { result } = renderHook(() => useUpdateNoteByPath(), { wrapper: w });
    await result.current.mutateAsync({ path: '20-contexts/work/a.md', body: 'x' });
    expect(backlinksInvalidated(spy)).toBe(true);
  });

  it('after a jot create and a jot update', async () => {
    request.mockResolvedValue({ ok: true, data: { id: 'manual-1', path: 'a.md', routingStatus: 'pending', updated: '' } });
    const create = spyClient();
    const c = renderHook(() => useCreateJot(), { wrapper: create.w });
    await c.result.current.mutateAsync({ body: 'x', route: false });
    expect(backlinksInvalidated(create.spy)).toBe(true);
    const update = spyClient();
    const u = renderHook(() => useUpdateJot(), { wrapper: update.w });
    await u.result.current.mutateAsync({ id: 'manual-1', body: 'y' });
    expect(backlinksInvalidated(update.spy)).toBe(true);
  });

  it('after a jot re-route', async () => {
    request.mockResolvedValue({ ok: true, data: { id: 'manual-1', path: 'b.md', context: 'work' } });
    const { spy, w } = spyClient();
    const { result } = renderHook(() => useRouteJot(), { wrapper: w });
    await result.current.mutateAsync({ id: 'manual-1', context: 'work' });
    expect(backlinksInvalidated(spy)).toBe(true);
  });

  it('after a jot delete', async () => {
    request.mockResolvedValue({ ok: true, data: null });
    const { spy, w } = spyClient();
    const { result } = renderHook(() => useDeleteJot(), { wrapper: w });
    await result.current.mutateAsync('manual-1');
    expect(backlinksInvalidated(spy)).toBe(true);
  });

  it('after a photo extract', async () => {
    request.mockResolvedValue({ ok: true, data: { id: 'manual-1', path: 'a.md', body: 'x', extracted: true } });
    const { spy, w } = spyClient();
    const { result } = renderHook(() => useExtractPhoto(), { wrapper: w });
    await result.current.mutateAsync({ jotId: 'manual-1', assetPath: 'assets/a.png' });
    expect(backlinksInvalidated(spy)).toBe(true);
  });
});
