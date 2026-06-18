import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { useMicrosoftAuthStatus, useStartMicrosoftAuth } from '../lib/api/hooks';

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('microsoft auth hooks', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('fetches status', async () => {
    vi.spyOn(client, 'get').mockResolvedValue({
      state: 'connected', account: 'me@tenant', error: null,
    });
    const { result } = renderHook(() => useMicrosoftAuthStatus(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.data?.state).toBe('connected'));
    expect(result.current.data?.account).toBe('me@tenant');
  });

  it('start posts to the start endpoint', async () => {
    const post = vi.spyOn(client, 'post').mockResolvedValue({ state: 'pending' });
    const { result } = renderHook(() => useStartMicrosoftAuth(), { wrapper: wrapper() });
    await result.current.mutateAsync();
    expect(post).toHaveBeenCalledWith('/v1/connectors/microsoft/auth/start');
  });
});
