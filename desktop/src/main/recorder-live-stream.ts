import type { Sidecar } from './sidecar';
import type { LiveTranscriptEvent } from '../shared/api-types';
import { createSseParser } from './chat-stream';

// One live-transcript stream per renderer (webContents id); subscribing
// again aborts the previous one.
const active = new Map<number, AbortController>();

/** Follow GET /v1/recorder/live until the sidecar sends `end` (recording
 *  finalised), the stream is stopped, or it errors. The sidecar sends a
 *  keepalive comment every 15s, which also keeps undici's body timeout away. */
export async function startRecorderLive(
  sidecar: Sidecar,
  key: number,
  send: (event: LiveTranscriptEvent) => void,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const info = sidecar.getInfo();
  if (!info) return { ok: false, error: 'Sidecar not ready' };
  active.get(key)?.abort();
  const ac = new AbortController();
  active.set(key, ac);
  try {
    const res = await fetch(`http://127.0.0.1:${info.port}/v1/recorder/live`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${info.token}` },
      signal: ac.signal,
    });
    if (!res.ok || !res.body) {
      let message = `HTTP ${res.status}`;
      try {
        const text = await res.text();
        if (text) {
          message = text.slice(0, 500);
          try {
            const parsed = JSON.parse(text);
            if (parsed && typeof parsed.detail === 'string') message = parsed.detail;
          } catch {
            // non-JSON body — keep the trimmed text
          }
        }
      } catch {
        // body unreadable — keep the bare status
      }
      return { ok: false, error: message };
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const parse = createSseParser();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const payload of parse(decoder.decode(value, { stream: true }))) {
        try {
          send(JSON.parse(payload) as LiveTranscriptEvent);
        } catch {
          // skip a malformed event; the stream itself is still healthy
        }
      }
    }
    return { ok: true };
  } catch (err) {
    if (ac.signal.aborted) return { ok: true };
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  } finally {
    if (active.get(key) === ac) active.delete(key);
  }
}

export function stopRecorderLive(key: number): void {
  active.get(key)?.abort();
  active.delete(key);
}
