import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { createServer, type Server, type IncomingMessage, type ServerResponse } from 'node:http';
import { forward, isAllowedMethod, isSafeApiPath } from '../api-forwarder';
import type { Sidecar } from '../sidecar';

// forward() must not ride on global fetch: undici's dispatcher enforces a
// hidden 300s headersTimeout that fires before any generous AbortSignal,
// killing long non-streaming sidecar calls (llm/run briefing synthesis) with
// an opaque "fetch failed". These tests run against a real HTTP server so the
// transport's actual timeout behavior is what's under test.

let server: Server;
let port = 0;
let lastReq: { method?: string; url?: string; headers: IncomingMessage['headers']; body: string };

function route(req: IncomingMessage, res: ServerResponse): void {
  let body = '';
  req.on('data', (c) => (body += c));
  req.on('end', () => {
    lastReq = { method: req.method, url: req.url, headers: req.headers, body };
    const url = req.url ?? '';
    if (url.startsWith('/v1/no-content')) {
      res.statusCode = 204;
      res.end();
    } else if (url.startsWith('/v1/fastapi-error')) {
      res.statusCode = 412;
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({ detail: 'recorder routing gate: fix your config' }));
    } else if (url.startsWith('/v1/plain-error')) {
      res.statusCode = 500;
      res.end('boom');
    } else if (url.startsWith('/v1/slow-headers')) {
      // Server thinks for a while before sending ANY bytes — the llm/run shape.
      setTimeout(() => {
        res.setHeader('Content-Type', 'application/json');
        res.end(JSON.stringify({ ok: 'slow' }));
      }, 1_500);
    } else if (url.startsWith('/v1/stall-forever')) {
      // Never respond; the configured timeoutMs must be the ceiling.
    } else {
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify({ echo: body ? JSON.parse(body) : null }));
    }
  });
}

beforeAll(async () => {
  server = createServer(route);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const addr = server.address();
  if (addr && typeof addr === 'object') port = addr.port;
});

afterAll(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

const sidecar = () =>
  ({ getInfo: () => ({ port, token: 'test-token' }) }) as unknown as Sidecar;

describe('api forwarder', () => {
  it('forwards PATCH with a JSON body and bearer token', async () => {
    const result = await forward(sidecar(), 'PATCH', '/v1/notes/manual-x', { body: 'new' });
    expect(result).toEqual({ ok: true, data: { echo: { body: 'new' } } });
    expect(lastReq.method).toBe('PATCH');
    expect(lastReq.url).toBe('/v1/notes/manual-x');
    expect(lastReq.headers.authorization).toBe('Bearer test-token');
    expect(lastReq.headers['content-type']).toBe('application/json');
  });

  it('forwards DELETE with no body and returns ok on 204', async () => {
    const result = await forward(sidecar(), 'DELETE', '/v1/no-content');
    expect(result).toEqual({ ok: true, data: null });
    expect(lastReq.headers['content-type']).toBeUndefined();
  });

  it('extracts FastAPI detail from error bodies', async () => {
    const result = await forward(sidecar(), 'POST', '/v1/fastapi-error', {});
    expect(result).toEqual({
      ok: false,
      error: 'recorder routing gate: fix your config',
      status: 412,
    });
  });

  it('passes through non-JSON error bodies', async () => {
    const result = await forward(sidecar(), 'GET', '/v1/plain-error');
    expect(result).toEqual({ ok: false, error: 'boom', status: 500 });
  });

  it('waits out header-less thinking time when timeoutMs allows it', async () => {
    // With undici this class of request dies at its hidden 300s headersTimeout
    // no matter how large timeoutMs is; the transport must have no ceiling
    // other than timeoutMs itself.
    const result = await forward(sidecar(), 'POST', '/v1/slow-headers', {}, 10_000);
    expect(result).toEqual({ ok: true, data: { ok: 'slow' } });
  });

  it('fails with a clear timeout error when timeoutMs elapses', async () => {
    const result = await forward(sidecar(), 'POST', '/v1/stall-forever', {}, 500);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toMatch(/timed out after 500ms/);
    }
  });

  it('reports sidecar not ready when there is no info', async () => {
    const none = { getInfo: () => null } as unknown as Sidecar;
    const result = await forward(none, 'GET', '/v1/anything');
    expect(result).toEqual({ ok: false, error: 'Sidecar not ready' });
  });
});

describe('isSafeApiPath', () => {
  it('accepts vault-relative api paths', () => {
    expect(isSafeApiPath('/v1/notes?path=Familiar/memory.md')).toBe(true);
  });
  it('rejects paths not starting with /', () => {
    expect(isSafeApiPath('v1/notes')).toBe(false);
    expect(isSafeApiPath('http://evil/v1')).toBe(false);
  });
  it('rejects traversal', () => {
    expect(isSafeApiPath('/v1/../admin')).toBe(false);
  });
});

describe('isAllowedMethod', () => {
  it('includes PUT', () => {
    expect(isAllowedMethod('PUT')).toBe(true);
  });
});
