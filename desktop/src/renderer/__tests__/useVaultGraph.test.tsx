import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useVaultGraph } from '../lib/api/hooks';

const request = vi.fn();
beforeEach(() => {
  request.mockReset();
  (globalThis as any).window = Object.assign((globalThis as any).window ?? {}, {
    gb: { api: { request } },
  });
});

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('useVaultGraph', () => {
  it('fetches the vault graph', async () => {
    request.mockResolvedValue({ ok: true, data: { nodes: [], edges: [], regions: [] } });
    const { result } = renderHook(() => useVaultGraph(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(request).toHaveBeenCalledWith('GET', '/v1/vault/graph');
    expect(result.current.data).toEqual({ nodes: [], edges: [], regions: [] });
  });
});
