import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiError, patch } from '../lib/api/client';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  window.gb = { ...window.gb, api: { request: apiRequest } } as typeof window.gb;
});

describe('patch', () => {
  it('passes ifMatch as the 4th bridge argument', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { etag: 'bbbbbbbbbbbbbbbb' } });
    await patch('/v1/notes/body', { path: 'a.md', body: 'x' }, { ifMatch: 'aaaaaaaaaaaaaaaa' });
    expect(apiRequest).toHaveBeenCalledWith(
      'PATCH',
      '/v1/notes/body',
      { path: 'a.md', body: 'x' },
      { ifMatch: 'aaaaaaaaaaaaaaaa' },
    );
  });

  it('omits the 4th argument when there is no etag', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: {} });
    await patch('/v1/notes/body', { path: 'a.md', body: 'x' }, { ifMatch: null });
    expect(apiRequest.mock.calls[0]).toHaveLength(3);
  });

  it('throws ApiError carrying the status', async () => {
    apiRequest.mockResolvedValue({ ok: false, error: 'note changed', status: 409 });
    const err = await patch('/v1/notes/x', { body: 'x' }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
  });
});
