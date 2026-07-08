import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useStartAuth } from '../lib/api/hooks';

const request = vi.fn();
beforeEach(() => {
  request.mockReset();
  window.gb = { ...window.gb, api: { request } } as typeof window.gb;
});

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('useStartAuth', () => {
  it('posts to the start endpoint', async () => {
    request.mockResolvedValue({
      ok: true,
      data: {
        session_id: 's',
        status: 'waiting_input',
        account: null,
        error: null,
        next: { kind: 'need_input', fields: [], auth_url: null, verification_uri: null, user_code: null, message: null },
      },
    });
    const { result } = renderHook(() => useStartAuth(), { wrapper });
    result.current.mutate({ id: 'slack', params: {} });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(request).toHaveBeenCalledWith('POST', '/v1/connectors/slack/auth/start', { params: {} });
    expect(result.current.data?.session_id).toBe('s');
  });
});
