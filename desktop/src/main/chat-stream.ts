import type { Sidecar } from './sidecar';
import type { ChatStreamEvent } from '../shared/api-types';

/** Incremental SSE parser: feed text chunks, get back complete `data:`
 *  payloads. Stateful per stream — create one per request. */
export function createSseParser(): (chunk: string) => string[] {
  let buffer = '';
  return (chunk: string) => {
    buffer += chunk;
    const out: string[] = [];
    let idx: number;
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      for (const line of block.split('\n')) {
        if (line.startsWith('data: ')) out.push(line.slice(6));
        else if (line.startsWith('data:')) out.push(line.slice(5));
      }
    }
    return out;
  };
}

// One in-flight stream per conversation; sending again aborts the previous.
const active = new Map<string, AbortController>();

export async function startChatStream(
  sidecar: Sidecar,
  convId: string,
  text: string,
  send: (event: ChatStreamEvent) => void,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const info = sidecar.getInfo();
  if (!info) return { ok: false, error: 'Sidecar not ready' };
  active.get(convId)?.abort();
  const ac = new AbortController();
  active.set(convId, ac);
  try {
    const res = await fetch(
      `http://127.0.0.1:${info.port}/v1/chat/${encodeURIComponent(convId)}/messages`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${info.token}`,
        },
        body: JSON.stringify({ text }),
        // No timeout: agent turns are long-lived. The sidecar enforces its
        // own 5-minute turn ceiling; stop() aborts from our side.
        signal: ac.signal,
      },
    );
    if (!res.ok || !res.body) {
      return { ok: false, error: `HTTP ${res.status}` };
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const parse = createSseParser();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const payload of parse(decoder.decode(value, { stream: true }))) {
        try {
          send(JSON.parse(payload) as ChatStreamEvent);
        } catch {
          // skip malformed event; the stream itself is still healthy
        }
      }
    }
    return { ok: true };
  } catch (err) {
    if (ac.signal.aborted) return { ok: true }; // user pressed stop
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  } finally {
    if (active.get(convId) === ac) active.delete(convId);
  }
}

export function stopChatStream(convId: string): void {
  active.get(convId)?.abort();
  active.delete(convId);
}
