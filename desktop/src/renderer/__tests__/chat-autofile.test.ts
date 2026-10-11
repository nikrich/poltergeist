import { describe, it, expect, vi } from 'vitest';
import { waitForAutoFile } from '../lib/chat-autofile';
import type { Conversation } from '../../shared/api-types';

const conv = (auto_filed: Conversation['auto_filed'], context: string | null = null) =>
  ({ id: 'c1', title: 't', created_at: 0, updated_at: 0, claude_session_id: null, messages: [],
     context, project: null, folder: null, auto_filed }) as Conversation;
const sleep = () => Promise.resolve();

describe('waitForAutoFile', () => {
  it('polls until auto-filing settles', async () => {
    const fetchConv = vi.fn()
      .mockResolvedValueOnce(conv('pending'))
      .mockResolvedValueOnce(conv('done', 'work'));
    const out = await waitForAutoFile('c1', fetchConv, { sleep });
    expect(out?.context).toBe('work');
    expect(fetchConv).toHaveBeenCalledTimes(2);
  });
  it('gives up after maxTries', async () => {
    const fetchConv = vi.fn().mockResolvedValue(conv('pending'));
    expect(await waitForAutoFile('c1', fetchConv, { sleep, maxTries: 3 })).toBeNull();
    expect(fetchConv).toHaveBeenCalledTimes(3);
  });
  it('returns null when the fetch fails', async () => {
    const fetchConv = vi.fn().mockRejectedValue(new Error('gone'));
    expect(await waitForAutoFile('c1', fetchConv, { sleep })).toBeNull();
  });
});
