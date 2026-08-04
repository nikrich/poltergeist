import { describe, it, expect, vi } from 'vitest';

// The handler factory is pure over its deps; we test it directly (no ipcMain).
import { makeSidecarHandler } from '../ipc';

describe('gb:plugins:sidecar guards', () => {
  const forward = vi.fn(async () => ({ ok: true as const, data: { hi: 1 } }));
  const handler = makeSidecarHandler({
    forward: forward as never,
    isAllowedMethod: (m: string) => ['GET', 'POST', 'PATCH', 'DELETE'].includes(m),
    demo: false,
    handleDemoApi: vi.fn(),
  });

  it('rejects non-/v1 paths', async () => {
    expect(await handler('GET', '/etc/passwd')).toEqual({
      ok: false,
      error: expect.stringContaining('/v1/'),
    });
    expect(forward).not.toHaveBeenCalled();
  });

  it('rejects disallowed methods', async () => {
    expect(await handler('OPTIONS', '/v1/import/jira/issues')).toEqual({
      ok: false,
      error: expect.stringContaining('Method'),
    });
  });

  it('forwards a valid /v1 GET (method upper-cased)', async () => {
    const r = await handler('get', '/v1/import/confluence/spaces');
    expect(forward).toHaveBeenCalledWith('GET', '/v1/import/confluence/spaces', undefined);
    expect(r).toEqual({ ok: true, data: { hi: 1 } });
  });

  it('uses the demo handler in demo mode', async () => {
    const demoFn = vi.fn(async () => ({ ok: true as const, data: 'demo' }));
    const h = makeSidecarHandler({
      forward: forward as never,
      isAllowedMethod: () => true,
      demo: true,
      handleDemoApi: demoFn as never,
    });
    expect(await h('GET', '/v1/x')).toEqual({ ok: true, data: 'demo' });
  });

  it('rejects a non-string path/method', async () => {
    expect(await handler(5 as never, '/v1/x')).toEqual({ ok: false, error: 'Invalid request shape' });
  });
});
