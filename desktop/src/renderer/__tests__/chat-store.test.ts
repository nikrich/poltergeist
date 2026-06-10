import { beforeEach, describe, expect, it } from 'vitest';
import { useChat } from '../stores/chat';

describe('chat store', () => {
  beforeEach(() => {
    useChat.setState({ activeId: null, streams: {}, errors: {} });
  });

  it('beginStream snapshots the pending user text and clears prior error', () => {
    useChat.setState({ errors: { c1: { message: 'old boom', userText: 'old q' } } });
    useChat.getState().beginStream('c1', 'my question');
    const s = useChat.getState();
    expect(s.streams.c1).toEqual({ userText: 'my question', text: '', tools: [] });
    expect(s.errors.c1).toBeUndefined();
  });

  it('delta events accumulate text', () => {
    useChat.getState().beginStream('c1', 'q');
    useChat.getState().applyEvent('c1', { type: 'delta', text: 'hel' });
    useChat.getState().applyEvent('c1', { type: 'delta', text: 'lo' });
    expect(useChat.getState().streams.c1?.text).toBe('hello');
  });

  it('tool events append chips', () => {
    useChat.getState().beginStream('c1', 'q');
    useChat.getState().applyEvent('c1', {
      type: 'tool',
      name: 'search',
      summary: 'searched vault: x',
    });
    expect(useChat.getState().streams.c1?.tools).toEqual([
      { name: 'search', summary: 'searched vault: x' },
    ]);
  });

  it('done clears the stream', () => {
    useChat.getState().beginStream('c1', 'q');
    useChat.getState().applyEvent('c1', { type: 'done', text: 'hello' });
    expect(useChat.getState().streams.c1).toBeUndefined();
  });

  it('error clears the stream and records the message', () => {
    useChat.getState().beginStream('c1', 'q');
    useChat.getState().applyEvent('c1', { type: 'error', message: 'boom' });
    expect(useChat.getState().streams.c1).toBeUndefined();
    expect(useChat.getState().errors.c1).toEqual({ message: 'boom', userText: 'q' });
  });

  it('error carries the originating user text for retry', () => {
    useChat.getState().beginStream('c1', 'what about refresh tokens?');
    useChat.getState().applyEvent('c1', { type: 'error', message: 'timeout' });
    expect(useChat.getState().errors.c1?.userText).toBe('what about refresh tokens?');
  });

  it('events for conversations without a stream are ignored', () => {
    useChat.getState().applyEvent('ghost', { type: 'delta', text: 'x' });
    expect(useChat.getState().streams.ghost).toBeUndefined();
  });

  it('endStream clears the stream without recording an error', () => {
    useChat.getState().beginStream('c1', 'q');
    useChat.getState().applyEvent('c1', { type: 'delta', text: 'par' });
    useChat.getState().endStream('c1');
    expect(useChat.getState().streams.c1).toBeUndefined();
    expect(useChat.getState().errors.c1).toBeUndefined();
  });

  it('endStream is a no-op when no stream exists', () => {
    useChat.getState().endStream('nope');
    expect(useChat.getState().streams).toEqual({});
  });
});
