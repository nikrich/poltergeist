/** Error from the sidecar API, carrying the HTTP status when one exists.
 * The main-process forwarder already extracts FastAPI's `detail` string and
 * the status code; previously the renderer threw a plain Error and dropped
 * the status — the import screen needs it to tell "409 connector not
 * configured" (call-to-action) apart from real failures (error panel). */
export class ApiError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

export async function get<T>(
  path: string,
  opts?: { signal?: AbortSignal },
): Promise<T> {
  // Honor signal at the renderer boundary — by the time we hit the IPC
  // bridge the request is already in flight in the main process. A
  // cancelled signal here at least prevents us from awaiting a result
  // whose query key has changed underneath us (React Query's main use
  // case: user clicked a different filter mid-fetch).
  if (opts?.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  const result = await window.gb.api.request<T>('GET', path);
  if (opts?.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
  if (!result.ok) throw new ApiError(result.error, result.status);
  return result.data;
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const result = await window.gb.api.request<T>('POST', path, body);
  if (!result.ok) throw new ApiError(result.error, result.status);
  return result.data;
}

export async function patch<T>(path: string, body?: unknown): Promise<T> {
  const result = await window.gb.api.request<T>('PATCH', path, body);
  if (!result.ok) throw new Error(result.error);
  return result.data;
}

export async function del<T = null>(path: string): Promise<T> {
  const result = await window.gb.api.request<T>('DELETE', path);
  if (!result.ok) throw new Error(result.error);
  return result.data as T;
}
