import { existsSync, readFileSync } from 'node:fs';
import { mkdir, readFile, realpath, rm, stat, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, extname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { compileFunction } from 'node:vm';
import type * as Esbuild from 'esbuild-wasm';
import type { DesignBuildResult } from '../shared/design-types';
import { isInsideVault } from './vault-paths';

// In-process bundler for live design prototypes: <dir>/src/main.tsx →
// <dir>/dist/{app.js,app.css,index.html}, served by gbproto://.
//
// esbuild-wasm's node entry spawns a `node` child process, which an installed
// app does not have (process.execPath is Electron). So we run its *browser*
// build in-process on a WebAssembly module we compile ourselves. That build
// has no file system: every import is resolved and loaded by the plugin below,
// which also enforces the rule that prototypes may only import react,
// react-dom and their own files. React comes from the app's own node_modules
// (read via fs, so it works from inside app.asar).

type EsbuildApi = typeof Esbuild;

const appRequire = createRequire(__filename);

const ALLOWED_BARE = new Set([
  'react',
  'react-dom',
  'react-dom/client',
  'react/jsx-runtime',
  'react/jsx-dev-runtime',
  'scheduler',
]);

const LOADERS: Record<string, Esbuild.Loader> = {
  '.ts': 'ts',
  '.tsx': 'tsx',
  '.js': 'js',
  '.jsx': 'jsx',
  '.mjs': 'js',
  '.css': 'css',
  '.json': 'json',
  '.svg': 'dataurl',
  '.png': 'dataurl',
  '.jpg': 'dataurl',
  '.jpeg': 'dataurl',
  '.gif': 'dataurl',
  '.webp': 'dataurl',
  '.woff': 'dataurl',
  '.woff2': 'dataurl',
};

const RESOLVE_EXTS = ['.tsx', '.ts', '.jsx', '.js', '.css', '.json'];
const MAX_ERROR_CHARS = 4000;

let esbuildReady: Promise<EsbuildApi> | null = null;

function loadEsbuild(): Promise<EsbuildApi> {
  if (!esbuildReady) {
    esbuildReady = (async () => {
      const file = appRequire.resolve('esbuild-wasm/lib/browser.js');
      // The browser build is a `(module => …)(module)` wrapper whose Go runtime
      // reads browser globals through `self`; hand it node's globalThis as
      // `self` in a private scope instead of defining a global `self` in main.
      const factory = compileFunction(readFileSync(file, 'utf8'), ['module', 'self'], {
        filename: file,
      });
      const mod: { exports: unknown } = { exports: {} };
      factory(mod, globalThis);
      const api = mod.exports as EsbuildApi;
      const wasm = readFileSync(appRequire.resolve('esbuild-wasm/esbuild.wasm'));
      const wasmModule = await WebAssembly.compile(wasm);
      await api.initialize({ wasmModule, worker: false });
      return api;
    })();
    esbuildReady.catch(() => {
      esbuildReady = null;
    });
  }
  return esbuildReady;
}

const isBare = (spec: string) => !spec.startsWith('.') && !spec.startsWith('/') && !isAbsolute(spec);

async function isFile(p: string): Promise<boolean> {
  try {
    return (await stat(p)).isFile();
  } catch {
    return false;
  }
}

/** Node-style resolution of a relative prototype import (extensions, index files). */
async function resolveRelative(base: string): Promise<string | null> {
  if (await isFile(base)) return base;
  for (const ext of RESOLVE_EXTS) if (await isFile(base + ext)) return base + ext;
  for (const ext of RESOLVE_EXTS) {
    const idx = join(base, `index${ext}`);
    if (await isFile(idx)) return idx;
  }
  return null;
}

function protoPlugin(protoRoot: string): Esbuild.Plugin {
  return {
    name: 'gb-prototype',
    setup(build) {
      build.onResolve({ filter: /.*/ }, async (args) => {
        if (args.kind === 'entry-point') return { path: args.path, namespace: 'proto' };

        // Inside React itself: plain node resolution from the importing file.
        if (args.namespace === 'appdep') {
          try {
            return { path: createRequire(args.importer).resolve(args.path), namespace: 'appdep' };
          } catch {
            return { errors: [{ text: `Cannot resolve ${args.path}` }] };
          }
        }

        const spec = args.path;
        // Remote stylesheets / fonts referenced from CSS stay remote.
        if (/^https?:\/\//i.test(spec) && (args.kind === 'url-token' || args.kind === 'import-rule')) {
          return { path: spec, external: true };
        }
        if (spec.startsWith('data:') && args.kind === 'url-token') return { path: spec, external: true };

        if (isBare(spec)) {
          if (ALLOWED_BARE.has(spec)) {
            return { path: appRequire.resolve(spec), namespace: 'appdep' };
          }
          return {
            errors: [{ text: `Only react, react-dom and relative imports are allowed: ${spec}` }],
          };
        }
        if (!spec.startsWith('.')) {
          return { errors: [{ text: `Only react, react-dom and relative imports are allowed: ${spec}` }] };
        }

        const found = await resolveRelative(resolve(dirname(args.importer), spec));
        if (!found) return { errors: [{ text: `Cannot find module ${spec}` }] };
        // Symlink guard: the real file must live inside the real prototype folder.
        const real = await realpath(found);
        if (!isInsideVault(protoRoot, real, { allowRoot: false })) {
          return { errors: [{ text: `Import outside the prototype folder: ${spec}` }] };
        }
        return { path: found, namespace: 'proto' };
      });

      build.onLoad({ filter: /.*/, namespace: 'proto' }, async (args) => {
        const loader = LOADERS[extname(args.path).toLowerCase()];
        if (!loader) return { errors: [{ text: `Unsupported file type: ${args.path}` }] };
        const bytes = await readFile(args.path);
        return {
          contents: loader === 'dataurl' ? new Uint8Array(bytes) : bytes.toString('utf8'),
          loader,
          resolveDir: dirname(args.path),
        };
      });

      build.onLoad({ filter: /.*/, namespace: 'appdep' }, async (args) => ({
        contents: await readFile(args.path, 'utf8'),
        loader: 'js',
        resolveDir: dirname(args.path),
      }));
    },
  };
}

function formatMessages(dir: string, messages: Esbuild.Message[]): string {
  const lines = messages.map((m) => {
    const loc = m.location;
    if (!loc) return m.text;
    let file = loc.file.replace(/^proto:/, '');
    if (isAbsolute(file)) file = relative(dir, file).split(sep).join('/');
    return `${file}:${loc.line}:${loc.column + 1}: ${m.text}`;
  });
  const text = lines.join('\n');
  return text.length > MAX_ERROR_CHARS ? `${text.slice(0, MAX_ERROR_CHARS - 1)}…` : text;
}

// Runs inside the prototype frame: keeps scroll position across reloads (the
// parent stores the last y and posts it back after load), reports the hash
// route so the parent can carry it to the next rev, and surfaces runtime
// errors to the panel.
const HOST_SCRIPT = `(function () {
  function post(m) { try { parent.postMessage(m, '*'); } catch (e) {} }
  addEventListener('message', function (e) {
    var d = e.data;
    if (e.source === parent && d && d.type === 'gb-proto:scroll' && typeof d.y === 'number') scrollTo(0, d.y);
  });
  var t = 0;
  addEventListener('scroll', function () {
    if (t) return;
    t = setTimeout(function () { t = 0; post({ type: 'gb-proto:scroll', y: scrollY }); }, 100);
  }, { passive: true });
  function route() { post({ type: 'gb-proto:route', hash: location.hash }); }
  addEventListener('hashchange', route);
  route();
  addEventListener('error', function (e) {
    post({ type: 'gb-proto:error', message: String(e.message || e.error || 'Script error') });
  });
  addEventListener('unhandledrejection', function (e) {
    var r = e.reason;
    post({ type: 'gb-proto:error', message: String((r && r.message) || r) });
  });
})();`;

export function prototypeHtml(rev: number, hasCss: boolean): string {
  return [
    '<!doctype html>',
    '<html>',
    '<head>',
    '<meta charset="utf-8" />',
    '<meta name="viewport" content="width=device-width, initial-scale=1" />',
    '<link rel="stylesheet" href="../design-pack/tokens.css" />',
    ...(hasCss ? ['<link rel="stylesheet" href="app.css" />'] : []),
    `<script>${HOST_SCRIPT}</script>`,
    '</head>',
    '<body>',
    '<div id="root"></div>',
    `<script type="module" src="app.js?rev=${rev}"></script>`,
    '</body>',
    '</html>',
    '',
  ].join('\n');
}

async function build(dir: string, rev: number): Promise<DesignBuildResult> {
  const dist = join(dir, 'dist');
  const revFile = join(dist, '.rev');
  try {
    if (
      (await readFile(revFile, 'utf8')).trim() === String(rev) &&
      existsSync(join(dist, 'app.js')) &&
      existsSync(join(dist, 'index.html'))
    ) {
      return { ok: true, rev, url: `gbproto://proto/dist/index.html?rev=${rev}` };
    }
  } catch {
    // no cache yet
  }

  const entry = join(dir, 'src', 'main.tsx');
  if (!(await isFile(entry))) return { ok: false, rev, error: 'src/main.tsx not found' };

  let result: Esbuild.BuildResult<{ write: false }>;
  try {
    const esbuild = await loadEsbuild();
    result = await esbuild.build({
      entryPoints: [entry],
      bundle: true,
      write: false,
      format: 'esm',
      platform: 'browser',
      target: 'es2020',
      jsx: 'automatic',
      minify: false,
      outfile: join(dist, 'app.js'),
      define: { 'process.env.NODE_ENV': '"production"' },
      logLevel: 'silent',
      plugins: [protoPlugin(await realpath(dir))],
    });
  } catch (err) {
    const errors = (err as Partial<Esbuild.BuildFailure>)?.errors;
    if (Array.isArray(errors) && errors.length > 0) {
      return { ok: false, rev, error: formatMessages(dir, errors) };
    }
    return { ok: false, rev, error: err instanceof Error ? err.message : String(err) };
  }

  const js = result.outputFiles.find((f) => f.path.endsWith('.js'));
  const css = result.outputFiles.find((f) => f.path.endsWith('.css'));
  if (!js) return { ok: false, rev, error: 'Bundler produced no JavaScript' };

  await mkdir(dist, { recursive: true });
  // Invalidate the cache marker first so a half-written dist never looks current.
  await rm(revFile, { force: true });
  await writeFile(join(dist, 'app.js'), js.contents);
  if (css) await writeFile(join(dist, 'app.css'), css.contents);
  else await rm(join(dist, 'app.css'), { force: true });
  await writeFile(join(dist, 'index.html'), prototypeHtml(rev, Boolean(css)));
  await writeFile(revFile, String(rev));
  return { ok: true, rev, url: `gbproto://proto/dist/index.html?rev=${rev}` };
}

// One build at a time per prototype folder.
const queues = new Map<string, Promise<unknown>>();

export function bundlePrototype(prototypeDir: string, rev: number): Promise<DesignBuildResult> {
  const dir = resolve(prototypeDir);
  const prev = queues.get(dir) ?? Promise.resolve();
  const next = prev.then(() =>
    build(dir, rev).catch(
      (err: unknown): DesignBuildResult => ({
        ok: false,
        rev,
        error: err instanceof Error ? err.message : String(err),
      }),
    ),
  );
  queues.set(dir, next);
  void next.finally(() => {
    if (queues.get(dir) === next) queues.delete(dir);
  });
  return next;
}
