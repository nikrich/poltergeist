import { describe, it, expect, vi, beforeEach } from 'vitest';
import { startRecorderStream, stopRecorderStream } from '../recorder-stream';
import type { Sidecar } from '../sidecar';
import type { LiveTranscriptEvent } from '../../shared/api-types';

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

const sidecar = { getInfo: () => ({ port: 4242, token: 't' }) } as unknown as Sidecar;
const notReady = { getInfo: () => null } as unknown as Sidecar;

function stream(text: string): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      // Split mid-event to prove the parser buffers across chunks.
      const mid = Math.floor(text.length / 2);
      c.enqueue(enc.encode(text.slice(0, mid)));
      c.enqueue(enc.encode(text.slice(mid)));
      c.close();
    },
  });
}

describe('startRecorderStream', () => {
  it('fails fast when the sidecar is not ready', async () => {
    expect(await startRecorderStream(notReady, '/v1/recorder/live', 1, vi.fn())).toEqual({
      ok: false,
      error: 'Sidecar not ready',
    });
  });

  it('GETs /v1/recorder/live and forwards events, skipping keepalives', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: stream(
        'data: {"type":"segment","seq":1,"t0":0,"t1":2,"text":"hallo","lang":"af"}\n\n' +
          ': keepalive\n\n' +
          'data: {"type":"end"}\n\n',
      ),
    });
    const events: LiveTranscriptEvent[] = [];
    const res = await startRecorderStream<LiveTranscriptEvent>(sidecar, '/v1/recorder/live', 1, (e) =>
      events.push(e),
    );
    expect(res).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://127.0.0.1:4242/v1/recorder/live');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer t');
    expect(events).toEqual([
      { type: 'segment', seq: 1, t0: 0, t1: 2, text: 'hallo', lang: 'af' },
      { type: 'end' },
    ]);
  });

  it('surfaces an HTTP error', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 501, body: null, text: async () => '{"detail":"nope"}' });
    expect(await startRecorderStream(sidecar, '/v1/recorder/live', 1, vi.fn())).toEqual({ ok: false, error: 'nope' });
  });

  it('stop aborts quietly', async () => {
    fetchMock.mockImplementationOnce(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(new Error('aborted')));
        }),
    );
    const p = startRecorderStream(sidecar, '/v1/recorder/live', 7, vi.fn());
    stopRecorderStream('/v1/recorder/live', 7);
    expect(await p).toEqual({ ok: true });
  });
});

describe('two streams for one window', () => {
  it('live and levels run side by side; stopping one leaves the other', async () => {
    const pending = (_url: string, init: RequestInit) =>
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(new Error('aborted')));
      });
    fetchMock.mockImplementation(pending);
    const live = startRecorderStream(sidecar, '/v1/recorder/live', 3, vi.fn());
    const levels = startRecorderStream(sidecar, '/v1/recorder/levels', 3, vi.fn());
    expect((fetchMock.mock.calls[1] as [string])[0]).toBe('http://127.0.0.1:4242/v1/recorder/levels');
    stopRecorderStream('/v1/recorder/levels', 3);
    expect(await levels).toEqual({ ok: true });
    const liveSignal = (fetchMock.mock.calls[0] as [string, RequestInit])[1].signal!;
    expect(liveSignal.aborted).toBe(false);
    stopRecorderStream('/v1/recorder/live', 3);
    expect(await live).toEqual({ ok: true });
  });
});
