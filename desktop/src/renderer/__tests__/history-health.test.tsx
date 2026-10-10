import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { useUpdateNoteByPath } from '../lib/api/hooks';
import { reportHistoryHealth, resetHistoryHealthForTests } from '../lib/history-health';
import { useToasts } from '../stores/toast';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const patchMock = vi.mocked(client.patch);

afterEach(() => {
  resetHistoryHealthForTests();
  useToasts.setState({ toasts: [] });
  patchMock.mockReset();
});

const messages = () => useToasts.getState().toasts.map((t) => t.message);

describe('reportHistoryHealth', () => {
  it('toasts once per session when a save went through without history', () => {
    reportHistoryHealth({ historyOk: false });
    reportHistoryHealth({ historyOk: false });
    expect(messages()).toEqual(['history unavailable — your edits are saved, but no version was kept']);
  });

  it('stays quiet when history worked or the server predates the field', () => {
    reportHistoryHealth({ historyOk: true });
    reportHistoryHealth({});
    reportHistoryHealth(undefined);
    expect(messages()).toEqual([]);
  });

  it('is wired into the by-path save hook', async () => {
    patchMock.mockResolvedValue({ path: 'a.md', updated: null, etag: 'e', historyOk: false });
    const qc = new QueryClient();
    const { result } = renderHook(() => useUpdateNoteByPath(), {
      wrapper: ({ children }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>,
    });
    await result.current.mutateAsync({ path: 'a.md', body: 'x' });
    await waitFor(() => expect(messages()).toHaveLength(1));
  });
});
