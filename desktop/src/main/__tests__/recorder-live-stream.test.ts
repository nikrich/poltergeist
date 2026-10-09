import { describe, it, expect, vi, beforeEach } from 'vitest';
import { startRecorderLive, stopRecorderLive } from '../recorder-live-stream';
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

describe('startRecorderLive', () => {
  it('fails fast when the sidecar is not ready', async () => {
    expect(await startRecorderLive(notReady, 1, vi.fn())).toEqual({
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
    const res = await startRecorderLive(sidecar, 1, (e) => events.push(e));
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
    expect(await startRecorderLive(sidecar, 1, vi.fn())).toEqual({ ok: false, error: 'nope' });
  });

  it('stop aborts quietly', async () => {
    fetchMock.mockImplementationOnce(
      (_url: string, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(new Error('aborted')));
        }),
    );
    const p = startRecorderLive(sidecar, 7, vi.fn());
    stopRecorderLive(7);
    expect(await p).toEqual({ ok: true });
  });
});
