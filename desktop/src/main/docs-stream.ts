import type { Sidecar } from './sidecar';
import type { DocsAssistEvent, DocsAssistRequest } from '../shared/api-types';
import { createSseParser } from './chat-stream';

// One in-flight stream per key; sending again with the same key aborts the
// previous. Keys: inline AI's stream_id, else the jot id (docs panel), else
// `path:<path>` — so the panel and inline AI on one jot never collide.
const active = new Map<string, AbortController>();

export const STREAM_ID_RE = /^[A-Za-z0-9][A-Za-z0-9:_-]{0,79}$/;

export function docsStreamKey(req: DocsAssistRequest): string {
  return req.stream_id ?? req.jot_id ?? `path:${req.path ?? ''}`;
}

export function isDocsAssistRequest(req: unknown): req is DocsAssistRequest {
  if (typeof req !== 'object' || req === null) return false;
  const r = req as Record<string, unknown>;
  const hasJot = typeof r.jot_id === 'string' && r.jot_id !== '';
  const hasPath = typeof r.path === 'string' && r.path !== '';
  if (hasJot === hasPath) return false;
  if (typeof r.mode !== 'string') return false;
  if (r.stream_id !== undefined && (typeof r.stream_id !== 'string' || !STREAM_ID_RE.test(r.stream_id))) {
    return false;
  }
  return true;
}

export async function startDocsStream(
  sidecar: Sidecar,
  req: DocsAssistRequest,
  send: (event: DocsAssistEvent) => void,
): Promise<{ ok: true } | { ok: false; error: string }> {
  const info = sidecar.getInfo();
  if (!info) return { ok: false, error: 'Sidecar not ready' };
  const key = docsStreamKey(req);
  active.get(key)?.abort();
  const ac = new AbortController();
  active.set(key, ac);
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
    // Deliberate abort: user pressed stop, or a re-send for this key
    // aborted us (the OLD invoke lands here and resolves {ok:true} harmlessly).
    if (ac.signal.aborted) return { ok: true };
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  } finally {
    if (active.get(key) === ac) active.delete(key);
  }
}

export function stopDocsStream(key: string): void {
  active.get(key)?.abort();
  active.delete(key);
}
