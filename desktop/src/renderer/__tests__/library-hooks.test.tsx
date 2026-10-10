import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../lib/api/client', () => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() }));

import * as client from '../lib/api/client';
import { useLibraryTree } from '../lib/api/hooks';
import { doc, libraryFixture } from './fixtures/library';

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('useLibraryTree polling', () => {
  afterEach(() => vi.useRealTimers());

  it('polls while a summary is pending and stops when done', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const pending = libraryFixture();
    pending.scopes[1]!.folders[1]!.docs = [doc({ summary_state: 'pending' })];
    const done = libraryFixture();
    vi.mocked(client.get).mockResolvedValueOnce(pending as never).mockResolvedValue(done as never);
    renderHook(() => useLibraryTree(), { wrapper });
    await waitFor(() => expect(client.get).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect(client.get).toHaveBeenCalledTimes(2));
    await vi.advanceTimersByTimeAsync(6200);
    expect(client.get).toHaveBeenCalledTimes(2);
  });
});
