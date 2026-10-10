import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

vi.mock('electron', () => ({
  protocol: { handle: vi.fn(), registerSchemesAsPrivileged: vi.fn() },
  net: { fetch: vi.fn() },
}));

import {
  contentTypeFor,
  protoPathFromUrl,
  resolveProtoPath,
  resolveServedFile,
  rootUrl,
  serveRoot,
  splitServedUrl,
} from '../design-protocol';

const R = '/tmp/proto';

describe('resolveProtoPath', () => {
  it('maps a relative path inside the served root', () => {
    expect(resolveProtoPath(R, 'dist/index.html')).toBe(resolve(R, 'dist/index.html'));
    expect(resolveProtoPath(R, 'design-pack/fonts/a b.woff2')).toBe(resolve(R, 'design-pack/fonts/a b.woff2'));
  });

  it('rejects traversal, absolute and empty paths', () => {
    for (const rel of ['', '/etc/passwd', '../x', 'dist/../../x', 'dist/./a.js', 'dist//a.js', 'dist\\..\\..\\x', 'dist/']) {
      expect(resolveProtoPath(R, rel), rel).toBeNull();
    }
  });
});

describe('protoPathFromUrl', () => {
  it('decodes the pathname for the proto host', () => {
    expect(protoPathFromUrl(R, 'gbproto://proto/dist/app.js?rev=4')).toBe(resolve(R, 'dist/app.js'));
    expect(protoPathFromUrl(R, 'gbproto://proto/dist/a%20b.css')).toBe(resolve(R, 'dist/a b.css'));
  });

  it('rejects other hosts, encoded traversal and malformed escapes', () => {
    expect(protoPathFromUrl(R, 'gbproto://other/dist/app.js')).toBeNull();
    // URL parsing clamps dot segments at the root, so these stay inside it.
    expect(protoPathFromUrl(R, 'gbproto://proto/dist/%2e%2e/%2e%2e/x')).toBe(resolve(R, 'x'));
    expect(protoPathFromUrl(R, 'gbproto://proto/../../x')).toBe(resolve(R, 'x'));
    // An encoded slash decodes into a real '..' segment: refused.
    expect(protoPathFromUrl(R, 'gbproto://proto/..%2f..%2fx')).toBeNull();
    expect(protoPathFromUrl(R, 'gbproto://proto/%E0%A4%A')).toBe('bad-request');
  });
});

describe('contentTypeFor', () => {
  it('maps known extensions and falls back to octet-stream', () => {
    expect(contentTypeFor('/a/index.html')).toBe('text/html; charset=utf-8');
    expect(contentTypeFor('/a/app.js')).toBe('text/javascript; charset=utf-8');
    expect(contentTypeFor('/a/app.css')).toBe('text/css; charset=utf-8');
    expect(contentTypeFor('/a/x.SVG')).toBe('image/svg+xml');
    expect(contentTypeFor('/a/x.woff2')).toBe('font/woff2');
    expect(contentTypeFor('/a/x.json')).toBe('application/json');
    expect(contentTypeFor('/a/x.bin')).toBe('application/octet-stream');
  });
});

// Creating symlinks needs extra privileges on Windows.
describe.skipIf(process.platform === 'win32')('resolveServedFile (symlink guard)', () => {
  let tmp: string;
  let root: string;

  beforeAll(() => {
    tmp = mkdtempSync(join(tmpdir(), 'gb-design-proto-'));
    root = join(tmp, 'proto');
    mkdirSync(join(root, 'dist'), { recursive: true });
    writeFileSync(join(root, 'dist/index.html'), '<p>hi</p>');
    writeFileSync(join(tmp, 'secret.txt'), 'nope');
    symlinkSync(join(tmp, 'secret.txt'), join(root, 'dist/leak.txt'));
  });

  afterAll(() => rmSync(tmp, { recursive: true, force: true }));

  it('serves real files inside the root', async () => {
    const file = await resolveServedFile(root, 'gbproto://proto/dist/index.html?rev=1');
    expect(file).toMatch(/dist[/\\]index\.html$/);
  });

  it('refuses symlinks that point outside the root, missing files and no root', async () => {
    expect(await resolveServedFile(root, 'gbproto://proto/dist/leak.txt')).toBeNull();
    expect(await resolveServedFile(root, 'gbproto://proto/dist/missing.js')).toBeNull();
    expect(await resolveServedFile(null, 'gbproto://proto/dist/index.html')).toBeNull();
  });
});

describe('prototypeHeaders (network lockdown)', () => {
  it('serves every file with a CSP that blocks network exfiltration', async () => {
    const { prototypeHeaders } = await import('../design-protocol');
    const h = prototypeHeaders('/x/dist/index.html');
    const csp = h['content-security-policy'];
    expect(csp).toContain("connect-src 'none'");
    expect(csp).toContain("form-action 'none'");
    expect(csp).toMatch(/img-src [^;]*data:/);
    expect(csp).not.toMatch(/img-src [^;]*https:/);
    expect(csp).toMatch(/default-src 'self' gbproto:/);
    expect(h['cache-control']).toBe('no-store');
    expect(h['content-type']).toBe('text/html; charset=utf-8');
  });
});


describe('per-folder serving', () => {
  it('serves several folders at once under their own prefix', () => {
    const a = serveRoot('/vault/20-contexts/w/prototypes/a');
    const b = serveRoot('/vault/20-contexts/w/prototypes/b');
    expect(a).not.toBe(b);
    const urlA = rootUrl(a, 'gbproto://proto/dist/index.html?rev=2');
    expect(urlA).toBe(`gbproto://proto/${a}/dist/index.html?rev=2`);
    expect(splitServedUrl(urlA)).toEqual({
      root: '/vault/20-contexts/w/prototypes/a',
      url: 'gbproto://proto/dist/index.html?rev=2',
    });
    expect(splitServedUrl(`gbproto://proto/${b}/design-pack/tokens.css`)?.root).toBe('/vault/20-contexts/w/prototypes/b');
  });

  it('refuses unknown prefixes and unprefixed paths', () => {
    expect(splitServedUrl('gbproto://proto/0123456789abcdef/dist/index.html')).toBeNull();
    expect(splitServedUrl('gbproto://proto/dist/index.html')).toBeNull();
    expect(splitServedUrl('gbproto://other/x')).toBeNull();
  });
});
