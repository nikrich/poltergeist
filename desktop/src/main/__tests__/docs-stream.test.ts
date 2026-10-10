import { describe, it, expect, vi, beforeEach } from 'vitest';
import { docsStreamKey, isDocsAssistRequest, startDocsStream, stopDocsStream } from '../docs-stream';
import type { Sidecar } from '../sidecar';
import type { DocsAssistRequest, DocsAssistEvent } from '../../shared/api-types';

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

// Minimal Sidecar stub that satisfies getInfo()
const sidecar = {
  getInfo: () => ({ port: 4242, token: 'test-token' }),
} as unknown as Sidecar;

const sidecarNotReady = {
  getInfo: () => null,
} as unknown as Sidecar;

/** Build a minimal ReadableStream from SSE text for testing. */
function makeStream(sseText: string): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(sseText));
      controller.close();
    },
  });
}

const baseReq: DocsAssistRequest = {
  jot_id: 'jot-abc',
  mode: 'polish',
};

describe('startDocsStream', () => {
  it('returns {ok:false} when sidecar is not ready', async () => {
    const result = await startDocsStream(sidecarNotReady, baseReq, vi.fn());
    expect(result).toEqual({ ok: false, error: 'Sidecar not ready' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('POSTs to /v1/docs/assist with full request body and bearer token', async () => {
    const req: DocsAssistRequest = {
      jot_id: 'jot-1',
      mode: 'summarize',
      instruction: 'be brief',
      selection: 'some text',
    };
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: makeStream('data: {"type":"done","text":"hi"}\n\n'),
    });
    await startDocsStream(sidecar, req, vi.fn());
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://127.0.0.1:4242/v1/docs/assist');
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['Authorization']).toBe(
      'Bearer test-token',
    );
    expect(JSON.parse(init.body as string)).toEqual(req);
  });

  it('parses SSE events and calls send() for each', async () => {
    const events: DocsAssistEvent[] = [];
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: makeStream(
        'data: {"type":"delta","text":"Hello"}\n\ndata: {"type":"done","text":"Hello"}\n\n',
      ),
    });
    const result = await startDocsStream(sidecar, baseReq, (e) => events.push(e));
    expect(result).toEqual({ ok: true });
    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ type: 'delta', text: 'Hello' });
    expect(events[1]).toEqual({ type: 'done', text: 'Hello' });
  });

  it('skips malformed JSON payloads without aborting the stream', async () => {
    const events: DocsAssistEvent[] = [];
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: makeStream(
        'data: NOT_JSON\n\ndata: {"type":"done","text":"ok"}\n\n',
      ),
    });
    const result = await startDocsStream(sidecar, baseReq, (e) => events.push(e));
    expect(result).toEqual({ ok: true });
    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({ type: 'done', text: 'ok' });
  });

  it('returns {ok:false} on HTTP error and extracts FastAPI detail', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 422,
      body: null,
      text: async () => '{"detail":"jot not found"}',
    });
    const result = await startDocsStream(sidecar, baseReq, vi.fn());
    expect(result).toEqual({ ok: false, error: 'jot not found' });
  });

  it('returns {ok:false} on fetch network error', async () => {
    fetchMock.mockRejectedValueOnce(new Error('network down'));
    const result = await startDocsStream(sidecar, baseReq, vi.fn());
    expect(result).toEqual({ ok: false, error: 'network down' });
  });
});

describe('stopDocsStream', () => {
  it('aborts an in-flight stream and causes startDocsStream to return {ok:true}', async () => {
    // Simulate a stream that never ends until aborted.
    fetchMock.mockImplementationOnce(
      (_url: string, init: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          // Reject with an AbortError when the signal fires.
          (init.signal as AbortSignal).addEventListener('abort', () => {
            const err = new DOMException('The operation was aborted.', 'AbortError');
            reject(err);
          });
        }),
    );
    const pending = startDocsStream(sidecar, { jot_id: 'jot-stop', mode: 'draft' }, vi.fn());
    // Give the fetch a tick to register the signal listener before aborting.
    await Promise.resolve();
    stopDocsStream('jot-stop');
    const result = await pending;
    // Deliberate abort must surface as {ok:true} (user-initiated, not an error).
    expect(result).toEqual({ ok: true });
  });

  it('is a no-op when no stream is active for that jotId', () => {
    expect(() => stopDocsStream('non-existent')).not.toThrow();
  });
});

describe('stream keys (A5)', () => {
  it('docsStreamKey prefers stream_id, then jot_id, then the path', () => {
    expect(docsStreamKey({ jot_id: 'j1', stream_id: 'inline-1', mode: 'polish' })).toBe('inline-1');
    expect(docsStreamKey({ jot_id: 'j1', mode: 'polish' })).toBe('j1');
    expect(docsStreamKey({ path: '20-contexts/work/a.md', mode: 'continue' })).toBe(
      'path:20-contexts/work/a.md',
    );
  });

  it('isDocsAssistRequest wants exactly one target, a mode and a sane stream_id', () => {
    expect(isDocsAssistRequest({ jot_id: 'j1', mode: 'polish' })).toBe(true);
    expect(isDocsAssistRequest({ path: 'a.md', mode: 'continue', stream_id: 'inline-x' })).toBe(true);
    expect(isDocsAssistRequest({ mode: 'polish' })).toBe(false);
    expect(isDocsAssistRequest({ jot_id: 'j1', path: 'a.md', mode: 'polish' })).toBe(false);
    expect(isDocsAssistRequest({ jot_id: '', mode: 'polish' })).toBe(false);
    expect(isDocsAssistRequest({ jot_id: 'j1' })).toBe(false);
    expect(isDocsAssistRequest({ jot_id: 'j1', mode: 'polish', stream_id: 'a b' })).toBe(false);
    expect(isDocsAssistRequest({ jot_id: 'j1', mode: 'polish', stream_id: 7 })).toBe(false);
    expect(isDocsAssistRequest(null)).toBe(false);
  });

  it('a stream_id keys its own stream, so an inline turn never aborts the panel turn on the same jot', () => {
    const signals: AbortSignal[] = [];
    fetchMock.mockImplementation((_url: string, init: RequestInit) => {
      signals.push(init.signal as AbortSignal);
      return new Promise(() => {});
    });
    void startDocsStream(sidecar, { jot_id: 'j1', mode: 'polish' }, vi.fn());
    void startDocsStream(sidecar, { jot_id: 'j1', stream_id: 'inline-1', mode: 'continue' }, vi.fn());
    expect(signals).toHaveLength(2);
    expect(signals[0]!.aborted).toBe(false);
    stopDocsStream('inline-1');
    expect(signals[1]!.aborted).toBe(true);
    expect(signals[0]!.aborted).toBe(false);
    stopDocsStream('j1');
    expect(signals[0]!.aborted).toBe(true);
  });

  it('ignores SSE keepalive comments', async () => {
    const events: DocsAssistEvent[] = [];
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: makeStream(': keepalive\n\n: keepalive\n\ndata: {"type":"done","text":"x"}\n\n'),
    });
    await startDocsStream(sidecar, { path: 'a.md', stream_id: 'inline-2', mode: 'continue' }, (e) =>
      events.push(e),
    );
    expect(events).toEqual([{ type: 'done', text: 'x' }]);
  });
});
