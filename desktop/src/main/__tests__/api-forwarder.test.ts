import { describe, it, expect, vi, beforeEach } from 'vitest';
import { forward } from '../api-forwarder';
import type { Sidecar } from '../sidecar';

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

// Minimal Sidecar stub that satisfies getInfo()
const sidecar = {
  getInfo: () => ({ port: 4242, token: 'test-token' }),
} as unknown as Sidecar;

describe('api forwarder', () => {
  it('forwards PATCH with a JSON body', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ id: 'manual-x', path: 'p', updated: 't' }),
    });
    const result = await forward(sidecar, 'PATCH', '/v1/notes/manual-x', { body: 'new' });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/notes/manual-x'),
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ body: 'new' }),
      }),
    );
    expect(result.ok).toBe(true);
  });

  it('forwards DELETE with no body and returns ok on 204', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 204,
      json: async () => ({}),
    });
    const result = await forward(sidecar, 'DELETE', '/v1/notes/manual-x');
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/v1/notes/manual-x'),
      expect.objectContaining({ method: 'DELETE', body: undefined }),
    );
    const init = fetchMock.mock.calls[0]![1] as RequestInit;
    expect(init.headers).not.toHaveProperty('Content-Type');
    expect(result.ok).toBe(true);
  });
});
