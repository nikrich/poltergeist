import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { rendererCsp } from '../../shared/renderer-csp';
import {
  REMOTE_IMAGES_ENTRY,
  rendererEntry,
  rendererLoadTarget,
} from '../renderer-entry';

// The policy that shipped as a static <meta> before remote images became a
// setting. remoteImages=false must reproduce it character for character.
const LEGACY_POLICY =
  "default-src 'self'; script-src 'self' plugin:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com plugin:; img-src 'self' data: gbasset: gbdoc: plugin:; connect-src 'self' gbdoc: plugin:; frame-src gbproto: http://127.0.0.1:* http://localhost:*;";

const REMOTE_POLICY =
  "default-src 'self'; script-src 'self' plugin:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com plugin:; img-src 'self' data: gbasset: gbdoc: plugin: https:; connect-src 'self' gbdoc: plugin:; frame-src gbproto: http://127.0.0.1:* http://localhost:*;";

function metaCsp(file: string): string {
  const html = readFileSync(join('src/renderer', file), 'utf8');
  const m = html.match(/http-equiv="Content-Security-Policy"\s+content="([^"]*)"/);
  if (!m) throw new Error(`no CSP meta in ${file}`);
  return m[1]!;
}

describe('rendererCsp', () => {
  it('is exactly the legacy policy when remote images are off', () => {
    expect(rendererCsp({ remoteImages: false })).toBe(LEGACY_POLICY);
  });

  it('adds only https: to img-src when remote images are on', () => {
    expect(rendererCsp({ remoteImages: true })).toBe(REMOTE_POLICY);
  });

  it('never allows plain http: images, frames, fonts or scripts beyond the legacy set', () => {
    const on = rendererCsp({ remoteImages: true });
    const off = rendererCsp({ remoteImages: false });
    const directives = (p: string) =>
      Object.fromEntries(
        p
          .split(';')
          .map((d) => d.trim())
          .filter(Boolean)
          .map((d) => {
            const [name, ...vals] = d.split(/\s+/);
            return [name!, vals];
          }),
      );
    const a = directives(off);
    const b = directives(on);
    for (const name of Object.keys(a)) {
      if (name === 'img-src') continue;
      expect(b[name]).toEqual(a[name]);
    }
    expect(b['img-src']).toEqual([...a['img-src']!, 'https:']);
    expect(b['img-src']).not.toContain('http:');
  });
});

describe('OFF policy is the authoritative block', () => {
  const tokens = (policy: string, name: string) => {
    const d = policy.split(';').map((x) => x.trim()).find((x) => x.startsWith(`${name} `));
    if (!d) throw new Error(`no ${name}`);
    return d.split(/\s+/).slice(1);
  };

  it('img-src has no network source: no http:, https:, wildcard or host', () => {
    const img = tokens(rendererCsp({ remoteImages: false }), 'img-src');
    for (const t of img) {
      expect(t).not.toMatch(/^(https?:|\*|wss?:)/i);
      expect(t).not.toContain('*');
      expect(t).not.toContain('.');
      expect(t).not.toContain('//');
    }
    expect(img).toEqual(["'self'", 'data:', 'gbasset:', 'gbdoc:', 'plugin:']);
  });

  it('ON adds https: to img-src and nothing to default-src/connect-src/frame-src/media', () => {
    const on = rendererCsp({ remoteImages: true });
    expect(tokens(on, 'default-src')).toEqual(["'self'"]);
    expect(tokens(on, 'connect-src')).toEqual(["'self'", 'gbdoc:', 'plugin:']);
    expect(on).not.toMatch(/media-src|object-src \*|https:\/\/\*/);
    expect(on.match(/https:(?!\/\/)/g)).toEqual(['https:']);
  });

  it('the document main loads with the setting off (dev and prod) carries the OFF policy', () => {
    const prod = rendererLoadTarget({ remoteImages: false, rendererDir: 'r' });
    expect(prod.kind === 'file' && prod.path.endsWith('index.html')).toBe(true);
    const dev = rendererLoadTarget({ remoteImages: false, rendererDir: 'r', devServerUrl: 'http://localhost:5173' });
    // The dev server root serves src/renderer/index.html.
    expect(dev).toEqual({ kind: 'url', url: 'http://localhost:5173/' });
    expect(metaCsp('index.html')).toBe(LEGACY_POLICY);
  });
});

describe('renderer HTML entries carry the generated policy', () => {
  it('index.html blocks remote images (legacy policy)', () => {
    expect(metaCsp('index.html')).toBe(rendererCsp({ remoteImages: false }));
  });

  it(`${REMOTE_IMAGES_ENTRY} allows https images`, () => {
    expect(metaCsp(REMOTE_IMAGES_ENTRY)).toBe(rendererCsp({ remoteImages: true }));
  });

  it('the two entries are identical apart from the policy', () => {
    const strip = (f: string) =>
      readFileSync(join('src/renderer', f), 'utf8')
        .replace(/\r\n/g, '\n')
        .replace(/content="default-src[^"]*"/, 'content="CSP"');
    expect(strip(REMOTE_IMAGES_ENTRY)).toBe(strip('index.html'));
  });
});

describe('rendererEntry', () => {
  it('picks the blocking entry by default and the remote-images entry when on', () => {
    expect(rendererEntry(false)).toBe('index.html');
    expect(rendererEntry(true)).toBe(REMOTE_IMAGES_ENTRY);
  });
});

describe('rendererLoadTarget', () => {
  const rendererDir = join('opt', 'app', 'out', 'renderer');

  it('prod: loads the chosen file from the renderer dir', () => {
    expect(rendererLoadTarget({ remoteImages: false, rendererDir })).toEqual({
      kind: 'file',
      path: join(rendererDir, 'index.html'),
    });
    expect(rendererLoadTarget({ remoteImages: true, rendererDir })).toEqual({
      kind: 'file',
      path: join(rendererDir, REMOTE_IMAGES_ENTRY),
    });
  });

  it('prod: carries the current hash route across the reload', () => {
    expect(rendererLoadTarget({ remoteImages: true, rendererDir, hash: '#/settings' })).toEqual({
      kind: 'file',
      path: join(rendererDir, REMOTE_IMAGES_ENTRY),
      hash: '/settings',
    });
  });

  it('dev: loads the entry from the dev server, keeping the hash', () => {
    expect(
      rendererLoadTarget({
        remoteImages: false,
        rendererDir,
        devServerUrl: 'http://localhost:5173',
      }),
    ).toEqual({ kind: 'url', url: 'http://localhost:5173/' });
    expect(
      rendererLoadTarget({
        remoteImages: true,
        rendererDir,
        devServerUrl: 'http://localhost:5173/',
        hash: '#/x',
      }),
    ).toEqual({ kind: 'url', url: `http://localhost:5173/${REMOTE_IMAGES_ENTRY}#/x` });
  });
});
