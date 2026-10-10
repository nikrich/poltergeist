import { act, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import type React from 'react';
import * as client from '../lib/api/client';
import { useUpdateNoteByPath } from '../lib/api/hooks';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ...actual, patch: vi.fn().mockResolvedValue({ path: 'a.md', etag: 'bbbbbbbbbbbbbbbb' }) };
});
const patchMock = vi.mocked(client.patch);

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

describe('useUpdateNoteByPath', () => {
  it('sends the assistant actor only when given', async () => {
    const { result } = renderHook(() => useUpdateNoteByPath(), { wrapper });
    await act(() =>
      result.current.mutateAsync({ path: 'a.md', body: 'b', ifMatch: 'aaaaaaaaaaaaaaaa', actor: 'assistant' }),
    );
    expect(patchMock).toHaveBeenLastCalledWith('/v1/notes/body', { path: 'a.md', body: 'b' }, {
      ifMatch: 'aaaaaaaaaaaaaaaa',
      actor: 'assistant',
    });
    await act(() => result.current.mutateAsync({ path: 'a.md', body: 'c', ifMatch: 'aaaaaaaaaaaaaaaa' }));
    expect(patchMock).toHaveBeenLastCalledWith('/v1/notes/body', { path: 'a.md', body: 'c' }, {
      ifMatch: 'aaaaaaaaaaaaaaaa',
    });
  });
});
