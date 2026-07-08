import { build } from 'esbuild';

await build({
  entryPoints: ['src/main.js'],
  outfile: 'dist/main.cjs',
  bundle: true,
  platform: 'node',
  format: 'cjs',
  external: ['electron'],
});

await build({
  entryPoints: ['src/renderer.js'],
  outfile: 'dist/renderer.mjs',
  bundle: true,
  platform: 'browser',
  format: 'esm',
});
console.log('built dist/main.cjs + dist/renderer.mjs');
