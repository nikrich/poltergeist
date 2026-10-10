import { describe, it, expect, vi, beforeEach } from 'vitest';

// The handler factory is pure over its deps; we test it directly (no ipcMain).
import { makeSidecarHandler } from '../ipc';

const ACTOR = 'X-Poltergeist-Actor';

describe('gb:plugins:sidecar', () => {
  const forward = vi.fn(async () => ({ ok: true as const, data: { hi: 1 } }));
  const handler = makeSidecarHandler({
    forward: forward as never,
    isAllowedMethod: (m: string) => ['GET', 'POST', 'PATCH', 'DELETE', 'PUT'].includes(m),
    isKnownPlugin: (id: string) => id === 'familiar',
    demo: false,
    handleDemoApi: vi.fn(),
  });

  beforeEach(() => forward.mockClear());

  it('rejects non-/v1 paths', async () => {
    expect(await handler('familiar', 'GET', '/etc/passwd')).toEqual({
      ok: false,
      error: expect.stringContaining('/v1/'),
    });
    expect(forward).not.toHaveBeenCalled();
  });

  it('rejects disallowed methods', async () => {
    expect(await handler('familiar', 'OPTIONS', '/v1/import/jira/issues')).toEqual({
      ok: false,
      error: expect.stringContaining('Method'),
    });
  });

  it('forwards a valid /v1 call stamped with the plugin id', async () => {
    const r = await handler('familiar', 'get', '/v1/import/confluence/spaces');
    expect(forward).toHaveBeenCalledWith('GET', '/v1/import/confluence/spaces', undefined, {
      [ACTOR]: 'plugin:familiar',
    });
    expect(r).toEqual({ ok: true, data: { hi: 1 } });
  });

  it('passes a well-formed If-Match through', async () => {
    await handler('familiar', 'PUT', '/v1/notes', { path: 'a.md', content: 'x' }, {
      ifMatch: '0123456789abcdef',
    });
    expect(forward).toHaveBeenCalledWith('PUT', '/v1/notes', { path: 'a.md', content: 'x' }, {
      [ACTOR]: 'plugin:familiar',
      'If-Match': '"0123456789abcdef"',
    });
  });

  it('refuses an unknown or malformed plugin id', async () => {
    expect(await handler('someone-else', 'GET', '/v1/x')).toEqual({
      ok: false,
      error: 'unknown plugin',
    });
    expect(await handler(undefined, 'GET', '/v1/x')).toEqual({ ok: false, error: 'unknown plugin' });
    expect(forward).not.toHaveBeenCalled();
  });

  it('uses the demo handler in demo mode', async () => {
    const demoFn = vi.fn(async () => ({ ok: true as const, data: 'demo' }));
    const h = makeSidecarHandler({
      forward: forward as never,
      isAllowedMethod: () => true,
      isKnownPlugin: () => true,
      demo: true,
      handleDemoApi: demoFn as never,
    });
    expect(await h('familiar', 'GET', '/v1/x')).toEqual({ ok: true, data: 'demo' });
  });

  it('rejects a non-string path/method', async () => {
    expect(await handler('familiar', 5 as never, '/v1/x')).toEqual({
      ok: false,
      error: 'Invalid request shape',
    });
  });
});
