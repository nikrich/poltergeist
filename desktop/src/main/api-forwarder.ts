import { request } from 'node:http';
import type { Sidecar } from './sidecar';
import type { HttpMethod, WriteActor } from '../shared/types';

export type { HttpMethod };

export const ALLOWED_METHODS: readonly HttpMethod[] = [
  'GET',
  'POST',
  'PATCH',
  'DELETE',
  'PUT',
];

export function isAllowedMethod(method: string): method is HttpMethod {
  return (ALLOWED_METHODS as readonly string[]).includes(method);
}

/** Plugin-facing guard: sidecar paths only — absolute-from-root, no traversal. */
export function isSafeApiPath(path: string): boolean {
  return path.startsWith('/') && !path.includes('..');
}

export type ApiResult<T = unknown> =
  | { ok: true; data: T }
  | { ok: false; error: string; status?: number };

const ETAG_RE = /^[0-9a-f]{16}$/;

/** Spec B §2: who is writing. The sidecar reads it; a missing header = user. */
export const ACTOR_HEADER = 'X-Poltergeist-Actor';

/** Same rule as the plugin manifest id (shared/plugin-types.ts). */
const PLUGIN_ID_RE = /^[a-z][a-z0-9-]{1,31}$/;

function ifMatchFrom(opts: unknown): Record<string, string> {
  if (!opts || typeof opts !== 'object') return {};
  const ifMatch = (opts as { ifMatch?: unknown }).ifMatch;
  return typeof ifMatch === 'string' && ETAG_RE.test(ifMatch)
    ? { 'If-Match': `"${ifMatch}"` }
    : {};
}

/** Headers the renderer may ask the forwarder to set: If-Match (a 16-hex
 * etag, spec B §7) and the actor. The renderer may only claim `assistant`;
 * anything else is sent as `user`. Every other key is dropped. */
export function requestHeadersFrom(opts: unknown): Record<string, string> {
  const claimed = opts && typeof opts === 'object' ? (opts as { actor?: unknown }).actor : undefined;
  const actor: WriteActor | 'user' = claimed === 'assistant' ? 'assistant' : 'user';
  return { ...ifMatchFrom(opts), [ACTOR_HEADER]: actor };
}

/** Headers for a plugin's sidecar call (main-process `api.fetch` and the
 * renderer bridge): always `plugin:<id>`, plus If-Match. null for a string
 * that is not a plugin id. Best-effort (spec B §2): renderer-side plugin
 * code shares the renderer and could reach gb:api:request directly. */
export function pluginHeadersFrom(pluginId: string, opts?: unknown): Record<string, string> | null {
  if (!PLUGIN_ID_RE.test(pluginId)) return null;
  return { ...ifMatchFrom(opts), [ACTOR_HEADER]: `plugin:${pluginId}` };
}

// node:http, not fetch: undici (behind Node's fetch) enforces a hidden 300s
// headersTimeout that fires regardless of any AbortSignal. Non-streaming LLM
// endpoints (/v1/llm/run, /v1/answer) send no bytes until synthesis finishes,
// so long briefings died at exactly 5min with an opaque "fetch failed".
// With node:http the only ceiling is timeoutMs.
export async function forward<T = unknown>(
  sidecar: Sidecar,
  method: HttpMethod,
  path: string,
  body?: unknown,
  timeoutMs = 300_000,
  extraHeaders: Record<string, string> = {},
): Promise<ApiResult<T>> {
  const info = sidecar.getInfo();
  if (!info) return { ok: false, error: 'Sidecar not ready' };
  const hasBody = body !== undefined;
  const payload = hasBody ? JSON.stringify(body) : undefined;
  return new Promise((resolve) => {
    const req = request(
      {
        host: '127.0.0.1',
        port: info.port,
        path,
        method,
        headers: {
          ...extraHeaders,
          ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
          Authorization: `Bearer ${info.token}`,
        },
      },
      (res) => {
        let text = '';
        res.setEncoding('utf8');
        res.on('data', (chunk: string) => (text += chunk));
        res.on('end', () => {
          clearTimeout(timer);
          const status = res.statusCode ?? 0;
          if (status === 204) {
            resolve({ ok: true, data: null as T });
            return;
          }
          if (status < 200 || status >= 300) {
            // FastAPI errors come back as ``{"detail": "..."}`` — extract that
            // so the renderer can show a clean message instead of a raw JSON
            // envelope. The 412 recorder routing gate is the motivating case:
            // the body explains exactly how to fix it, and pasting it verbatim
            // into a toast is more useful than ``HTTP 412: {"detail":"..."}``.
            let message = text.slice(0, 500);
            try {
              const parsed = JSON.parse(text);
              if (parsed && typeof parsed.detail === 'string') {
                message = parsed.detail;
              }
            } catch {
              // Non-JSON body — fall through with the trimmed text.
            }
            resolve({ ok: false, error: message, status });
            return;
          }
          try {
            resolve({ ok: true, data: JSON.parse(text) as T });
          } catch (err) {
            resolve({ ok: false, error: err instanceof Error ? err.message : String(err) });
          }
        });
        res.on('error', fail);
      },
    );
    const fail = (err: unknown): void => {
      clearTimeout(timer);
      req.destroy();
      resolve({ ok: false, error: err instanceof Error ? err.message : String(err) });
    };
    const timer = setTimeout(() => {
      fail(new Error(`sidecar request timed out after ${timeoutMs}ms: ${method} ${path}`));
    }, timeoutMs);
    req.on('error', (err) => {
      // destroy() during our own timeout also emits an error; fail() already
      // resolved by then, and resolving a settled promise is a no-op.
      fail(err);
    });
    if (payload !== undefined) req.write(payload);
    req.end();
  });
}
