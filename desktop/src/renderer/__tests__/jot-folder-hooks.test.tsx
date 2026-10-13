import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { useCreateJotFolder, useDeleteJotFolder, useJotTree, useMoveJot, useMoveJotFolder } from '../lib/api/hooks';

type Call = { method: string; path: string; body: unknown };
let calls: Call[] = [];

beforeEach(() => {
  calls = [];
  window.gb.api.request = vi.fn(async (method: string, path: string, body?: unknown) => {
    calls.push({ method, path, body });
    if (path === '/v1/notes/tree') return { ok: true, data: { inbox: [], unrouted: [], scopes: [] } };
    return { ok: true, data: {} };
  }) as unknown as typeof window.gb.api.request;
});

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const spy = vi.spyOn(qc, 'invalidateQueries');
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  return { wrapper, spy };
}

describe('jot folder hooks', () => {
  it('loads the tree', async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useJotTree(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual({ inbox: [], unrouted: [], scopes: [] }));
  });

  it('sends each mutation and invalidates jots', async () => {
    const { wrapper, spy } = setup();
    const ref = { context: 'work', project: 'atlas', path: 'q4' };
    const move = renderHook(() => useMoveJot(), { wrapper }).result;
    const create = renderHook(() => useCreateJotFolder(), { wrapper }).result;
    const moveF = renderHook(() => useMoveJotFolder(), { wrapper }).result;
    const delF = renderHook(() => useDeleteJotFolder(), { wrapper }).result;
    await move.current.mutateAsync({ id: 'j1', context: 'work', project: null, folder: 'q4' });
    await create.current.mutateAsync(ref);
    await moveF.current.mutateAsync({ from: ref, to: { ...ref, path: 'q5' } });
    await delF.current.mutateAsync(ref);
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      'PATCH /v1/notes/j1/location',
      'POST /v1/notes/folders',
      'PATCH /v1/notes/folders',
      'DELETE /v1/notes/folders?context=work&path=q4&project=atlas',
    ]);
    expect(calls[0]!.body).toEqual({ context: 'work', project: null, folder: 'q4' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['jots'] });
  });
});
