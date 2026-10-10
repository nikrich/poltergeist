import { beforeEach, describe, expect, it, vi } from 'vitest';
import { subscribeAssistEvents } from '../lib/docs-assist-events';
import type { DocsAssistEvent } from '../../shared/api-types';

type Payload = { key?: string; jotId: string; event: DocsAssistEvent };
let listener: ((p: Payload) => void) | null = null;
const off = vi.fn();

beforeEach(() => {
  listener = null;
  off.mockClear();
  window.gb = {
    ...window.gb,
    on: ((channel: string, l: (p: Payload) => void) => {
      if (channel === 'docs:event') listener = l;
      return off;
    }) as unknown as typeof window.gb.on,
  };
});

function handlers() {
  return {
    onDelta: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
    onInterrupted: vi.fn(),
    onTool: vi.fn(),
  };
}

describe('subscribeAssistEvents', () => {
  it('routes each event type for its key', () => {
    const h = handlers();
    subscribeAssistEvents('inline-1', h);
    listener!({ key: 'inline-1', jotId: 'inline-1', event: { type: 'delta', text: 'a' } });
    listener!({ key: 'inline-1', jotId: 'inline-1', event: { type: 'tool', name: 'x', summary: 'searching' } });
    listener!({ key: 'inline-1', jotId: 'inline-1', event: { type: 'done', text: 'a' } });
    listener!({ key: 'inline-1', jotId: 'inline-1', event: { type: 'error', message: 'boom' } });
    listener!({ key: 'inline-1', jotId: 'inline-1', event: { type: 'error', message: 'stop', interrupted: true } });
    expect(h.onDelta).toHaveBeenCalledWith('a');
    expect(h.onTool).toHaveBeenCalledWith('searching');
    expect(h.onDone).toHaveBeenCalledWith('a');
    expect(h.onError).toHaveBeenCalledWith('boom');
    expect(h.onInterrupted).toHaveBeenCalledTimes(1);
  });

  it('ignores other keys and falls back to jotId for older payloads', () => {
    const h = handlers();
    subscribeAssistEvents('j1', h);
    listener!({ key: 'inline-9', jotId: 'inline-9', event: { type: 'delta', text: 'no' } });
    listener!({ jotId: 'j1', event: { type: 'delta', text: 'yes' } });
    expect(h.onDelta).toHaveBeenCalledTimes(1);
    expect(h.onDelta).toHaveBeenCalledWith('yes');
  });

  it('returns the bridge unsubscribe', () => {
    const unsub = subscribeAssistEvents('j1', handlers());
    unsub();
    expect(off).toHaveBeenCalledTimes(1);
  });
});
