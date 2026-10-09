import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useBacklinks } from '../lib/api/hooks';

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
