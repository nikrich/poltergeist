import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { useCreateFromTemplate, useRenderTemplate, useTemplates } from '../lib/api/hooks';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
});

describe('template hooks', () => {
  it('useTemplates fetches only when enabled', async () => {
    getMock.mockResolvedValue({ templates: [] });
    renderHook(() => useTemplates({ enabled: false }), { wrapper });
    expect(getMock).not.toHaveBeenCalled();
    const { result } = renderHook(() => useTemplates(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual({ templates: [] }));
    expect(getMock).toHaveBeenCalledWith('/v1/templates');
  });

  it('useCreateFromTemplate posts answers to the encoded id', async () => {
    postMock.mockResolvedValue({ path: 'a.md', title: 'A', etag: 'e', status: 'applied' });
    const { result } = renderHook(() => useCreateFromTemplate(), { wrapper });
    await result.current.mutateAsync({ id: 'one-on-one', answers: { person: 'Alex' } });
    expect(postMock).toHaveBeenCalledWith('/v1/templates/one-on-one/create', { answers: { person: 'Alex' } });
  });

  it('useRenderTemplate posts to /render', async () => {
    postMock.mockResolvedValue({ path: 'a.md', folder: 'f', filename: 'a.md', title: 'A', frontmatter: {}, body: 'B' });
    const { result } = renderHook(() => useRenderTemplate(), { wrapper });
    const res = await result.current.mutateAsync({ id: 'meeting-notes', answers: {} });
    expect(postMock).toHaveBeenCalledWith('/v1/templates/meeting-notes/render', { answers: {} });
    expect(res.body).toBe('B');
  });
});
