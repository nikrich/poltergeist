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

export async function forward<T = unknown>(
  sidecar: Sidecar,
  method: HttpMethod,
  path: string,
  body?: unknown,
  timeoutMs = 300_000,
): Promise<ApiResult<T>> {
  const info = sidecar.getInfo();
  if (!info) return { ok: false, error: 'Sidecar not ready' };
  try {
    const hasBody = body !== undefined;
    const res = await fetch(`http://127.0.0.1:${info.port}${path}`, {
      method,
      headers: {
        ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
        Authorization: `Bearer ${info.token}`,
      },
      body: hasBody ? JSON.stringify(body) : undefined,
      // 5min ceiling. /v1/answer (RAG + LLM synthesis) and the first /v1/search
      // call (cold-loads sentence-transformers) can legitimately take a minute
      // or two. Everything else returns in milliseconds; we'd rather wait too
      // long than chop off a genuine answer. Plugins may override this.
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (res.status === 204) {
      return { ok: true, data: null as T };
    }
    if (!res.ok) {
      const text = await res.text();
      // FastAPI errors come back as ``{"detail": "..."}`` — extract that so
      // the renderer can show a clean message instead of a raw JSON
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
      return { ok: false, error: message, status: res.status };
    }
    const data = (await res.json()) as T;
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}
