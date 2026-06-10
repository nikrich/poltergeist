import type { Sidecar } from './sidecar';
import type { DocsAssistEvent, DocsAssistRequest } from '../shared/api-types';
import { createSseParser } from './chat-stream';

// One in-flight stream per jot; sending again aborts the previous.
const active = new Map<string, AbortController>();

export async function startDocsStream(
  sidecar: Sidecar,
  req: DocsAssistRequest,
  send: (event: DocsAssistEvent) => void,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const info = sidecar.getInfo();
  if (!info) return { ok: false, error: 'Sidecar not ready' };
  active.get(req.jot_id)?.abort();
  const ac = new AbortController();
  active.set(req.jot_id, ac);
  try {
    const res = await fetch(
      `http://127.0.0.1:${info.port}/v1/docs/assist`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${info.token}`,
        },
        body: JSON.stringify(req),
        // No timeout: agent turns are long-lived. The sidecar enforces its
        // own ceiling; stop() aborts from our side.
        signal: ac.signal,
      },
    );
    if (!res.ok || !res.body) {
      // Mirror api-forwarder.ts: FastAPI errors come back as
      // ``{"detail": "..."}`` — surface that instead of a bare status code.
      let message = `HTTP ${res.status}`;
      try {
        const text = await res.text();
        if (text) {
          message = text.slice(0, 500);
          try {
            const parsed = JSON.parse(text);
            if (parsed && typeof parsed.detail === 'string') {
              message = parsed.detail;
            }
          } catch {
            // Non-JSON body — fall through with the trimmed text.
          }
        }
      } catch {
        // Body unreadable — keep the bare status.
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
          send(JSON.parse(payload) as DocsAssistEvent);
        } catch {
          // skip malformed event; the stream itself is still healthy
        }
      }
    }
    return { ok: true };
  } catch (err) {
    // Deliberate abort: user pressed stop, or a re-send for this jot
    // aborted us (the OLD invoke lands here and resolves {ok:true} harmlessly).
    if (ac.signal.aborted) return { ok: true };
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  } finally {
    if (active.get(req.jot_id) === ac) active.delete(req.jot_id);
  }
}

export function stopDocsStream(jotId: string): void {
  active.get(jotId)?.abort();
  active.delete(jotId);
}
