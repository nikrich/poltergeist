import type { Sidecar } from './sidecar';
import { createSseParser } from './chat-stream';

// One stream per (sidecar path, renderer webContents id); subscribing again
// aborts the previous one. A window follows both /v1/recorder/live and
// /v1/recorder/levels at once.
const active = new Map<string, AbortController>();
const slot = (path: string, key: number) => `${path}#${key}`;

/** Follow a recorder SSE route (`/v1/recorder/live`, `/v1/recorder/levels`)
 *  until the sidecar sends `end`, the stream is stopped, or it errors. The
 *  sidecar sends keepalive comments, which also keep undici's body timeout away. */
export async function startRecorderStream<E>(
  sidecar: Sidecar,
  path: string,
  key: number,
  send: (event: E) => void,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const info = sidecar.getInfo();
  if (!info) return { ok: false, error: 'Sidecar not ready' };
  const id = slot(path, key);
  active.get(id)?.abort();
  const ac = new AbortController();
  active.set(id, ac);
  try {
    const res = await fetch(`http://127.0.0.1:${info.port}${path}`, {
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
          send(JSON.parse(payload) as E);
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
    if (active.get(id) === ac) active.delete(id);
  }
}

export function stopRecorderStream(path: string, key: number): void {
  const id = slot(path, key);
  active.get(id)?.abort();
  active.delete(id);
}
