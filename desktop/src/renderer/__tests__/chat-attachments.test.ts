import { describe, expect, it, vi, beforeEach } from 'vitest';

import * as client from '../lib/api/client';
import { isAccepted, uploadAttachments } from '../lib/chat-attachments';

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));

describe('isAccepted', () => {
  it('accepts .md and .txt', () => {
    expect(isAccepted(new File(['x'], 'a.md', { type: 'text/markdown' }))).toBe(true);
    expect(isAccepted(new File(['x'], 'a.txt', { type: 'text/plain' }))).toBe(true);
  });
  it('rejects .png', () => {
    expect(isAccepted(new File(['x'], 'a.png', { type: 'image/png' }))).toBe(false);
  });
});

describe('uploadAttachments', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('posts files as base64 and returns attachments', async () => {
    const spy = vi.mocked(client.post).mockResolvedValue({
      attachments: [{ path: '20-contexts/chat-attachments/a.md', title: 'a.md', kind: 'text' }],
    } as never);
    const out = await uploadAttachments('conv1', [
      new File(['hello'], 'a.md', { type: 'text/markdown' }),
    ]);
    expect(out).toHaveLength(1);
    expect(spy).toHaveBeenCalledWith('/v1/chat/conv1/attachments', {
      files: [{ name: 'a.md', mime: 'text/markdown', content_b64: expect.any(String) }],
    });
  });
});
