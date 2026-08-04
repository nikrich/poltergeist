import { request } from 'node:http';
import type { Sidecar } from './sidecar';
import type { HttpMethod } from '../shared/types';

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
