import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { TextDecoder as NodeTextDecoder, TextEncoder as NodeTextEncoder } from 'node:util';
import { bundlePrototype } from '../design-bundler';

// Main tests share the jsdom environment, which swaps in its own Uint8Array
// and TextEncoder; esbuild-wasm asserts `encode() instanceof Uint8Array`.
// Electron main is plain node, so restore node's own realm for this file.
globalThis.Uint8Array = Object.getPrototypeOf(Buffer.prototype).constructor as Uint8ArrayConstructor;
globalThis.TextEncoder = NodeTextEncoder as typeof globalThis.TextEncoder;
globalThis.TextDecoder = NodeTextDecoder as typeof globalThis.TextDecoder;

let root: string;

function makeProto(name: string, files: Record<string, string>): string {
  const dir = join(root, name);
  for (const [rel, body] of Object.entries(files)) {
    const abs = join(dir, rel);
    mkdirSync(join(abs, '..'), { recursive: true });
    writeFileSync(abs, body);
  }
  return dir;
}

const MAIN = `import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles.css';
createRoot(document.getElementById('root')!).render(<App />);
`;

const APP = `import { useState } from 'react';
import logo from './logo.svg';
export function App() {
  const [n, setN] = useState(0);
  return <button onClick={() => setN(n + 1)}><img src={logo} />Clicked PROTO_MARKER {n}</button>;
}
`;

beforeAll(() => {
  root = mkdtempSync(join(tmpdir(), 'gb-design-bundler-'));
});

afterAll(() => {
  rmSync(root, { recursive: true, force: true });
});

describe('bundlePrototype', () => {
  it('bundles a React prototype with css, assets and the pack tokens', async () => {
    const dir = makeProto('ok', {
      'src/main.tsx': MAIN,
      'src/App.tsx': APP,
      'src/styles.css': '.btn { color: var(--accent); }',
      'src/logo.svg': '<svg xmlns="http://www.w3.org/2000/svg"/>',
      'design-pack/tokens.css': ':root { --accent: red; }',
    });
    const res = await bundlePrototype(dir, 3);
    expect(res).toEqual({ ok: true, rev: 3, url: 'gbproto://proto/dist/index.html?rev=3' });

    const js = readFileSync(join(dir, 'dist/app.js'), 'utf8');
    expect(js).toContain('PROTO_MARKER');
    expect(js).toContain('useState'); // React itself is bundled in
    expect(js).toContain('data:image/svg+xml');
    expect(js).not.toMatch(/process\.env\.NODE_ENV/);

    expect(readFileSync(join(dir, 'dist/app.css'), 'utf8')).toContain('.btn');

    const html = readFileSync(join(dir, 'dist/index.html'), 'utf8');
    expect(html).toContain('href="../design-pack/tokens.css"');
    expect(html).toContain('href="app.css"');
    expect(html).toContain('src="app.js?rev=3"');
    expect(html).toContain('<div id="root"></div>');
    expect(html).toContain('gb-proto:scroll');
    expect(html).toContain('gb-proto:error');
    expect(html).toContain('gb-proto:route');
    expect(html).toContain('hashchange');
  }, 60_000);

  it('returns the cached bundle when the rev is unchanged', async () => {
    const dir = join(root, 'ok');
    const before = statSync(join(dir, 'dist/app.js')).mtimeMs;
    const res = await bundlePrototype(dir, 3);
    expect(res.ok).toBe(true);
    expect(statSync(join(dir, 'dist/app.js')).mtimeMs).toBe(before);
  });

  it('rebuilds on a new rev and drops a stale stylesheet', async () => {
    const dir = join(root, 'ok');
    writeFileSync(join(dir, 'src/main.tsx'), MAIN.replace("import './styles.css';\n", ''));
    const res = await bundlePrototype(dir, 4);
    expect(res).toMatchObject({ ok: true, rev: 4 });
    expect(existsSync(join(dir, 'dist/app.css'))).toBe(false);
    const html = readFileSync(join(dir, 'dist/index.html'), 'utf8');
    expect(html).not.toContain('app.css');
    expect(html).toContain('app.js?rev=4');
  }, 60_000);

  it('reports syntax errors with file:line:col', async () => {
    const dir = makeProto('broken', {
      'src/main.tsx': "import { App } from './App';\nconsole.log(App);\n",
      'src/App.tsx': 'export function App() {\n  return <div>oops</span>;\n}\n',
    });
    const res = await bundlePrototype(dir, 1);
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.rev).toBe(1);
    expect(res.error).toMatch(/src\/App\.tsx:2:\d+: /);
  }, 60_000);

  it('rejects bare imports other than react', async () => {
    const dir = makeProto('lodash', {
      'src/main.tsx': "import _ from 'lodash';\nconsole.log(_);\n",
    });
    const res = await bundlePrototype(dir, 1);
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.error).toContain('Only react, react-dom and relative imports are allowed: lodash');
    expect(res.error).toMatch(/src\/main\.tsx:1:\d+: /);
  }, 60_000);

  it('refuses relative imports that escape the prototype folder', async () => {
    makeProto('outside', { 'secret.ts': 'export const s = 1;' });
    const dir = makeProto('escape', {
      'src/main.tsx': "import { s } from '../../outside/secret';\nconsole.log(s);\n",
    });
    const res = await bundlePrototype(dir, 1);
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.error).toContain('outside the prototype folder');
  }, 60_000);

  it('reports a missing relative module', async () => {
    const dir = makeProto('missing', {
      'src/main.tsx': "import { X } from './Nope';\nconsole.log(X);\n",
    });
    const res = await bundlePrototype(dir, 1);
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.error).toContain('./Nope');
  }, 60_000);
});
