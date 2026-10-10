import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useEgoGraph } from '../lib/api/hooks';
import type { EgoGraph } from '../../shared/api-types';

const request = vi.fn();
beforeEach(() => {
  request.mockReset();
  window.gb = { ...window.gb, api: { request } } as typeof window.gb;
});

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const EGO: EgoGraph = {
  focus: '20-contexts/work/a.md', depth: 2, truncated: false, indexing: false,
  nodes: [{ path: '20-contexts/work/a.md', title: 'A', context: 'work', kind: 'note', degree: 0, ghost: false, hop: 0 }],
  edges: [],
};

describe('useEgoGraph', () => {
  it('fetches the neighbourhood of a focus at a depth', async () => {
    request.mockResolvedValue({ ok: true, data: EGO });
    const { result } = renderHook(() => useEgoGraph('20-contexts/work/a.md', 2), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(request).toHaveBeenCalledWith('GET', '/v1/vault/graph?focus=20-contexts%2Fwork%2Fa.md&depth=2');
    expect(result.current.data).toEqual(EGO);
  });

  it('does not fetch without a focus', async () => {
    renderHook(() => useEgoGraph(null, 2), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(request).not.toHaveBeenCalled();
  });
});
