import { build } from 'esbuild';
import { copyFileSync, mkdirSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

await build({
  entryPoints: ['src/main.js'],
  outfile: 'dist/main.cjs',
  bundle: true,
  platform: 'node',
  format: 'cjs',
  external: ['electron'],
});

await build({
  entryPoints: ['src/renderer.jsx'],
  outfile: 'dist/renderer.mjs',
  bundle: true,
  platform: 'browser',
  format: 'esm',
  jsx: 'automatic',
  minify: true,
  define: { 'process.env.NODE_ENV': '"production"' },
});

// Courier Prime (SIL OFL) ships inside dist so the page view and the PDF use
// the real screenplay face. The renderer loads it via new URL('./fonts/', import.meta.url).
const fontSrc = 'node_modules/@fontsource/courier-prime/files';
const fonts = readdirSync(fontSrc).filter((f) => /^courier-prime-latin-(400|700)-(normal|italic)\.woff2$/.test(f));
if (fonts.length !== 4) throw new Error(`expected 4 Courier Prime woff2 files in ${fontSrc}, found ${fonts.length}`);
mkdirSync('dist/fonts', { recursive: true });
for (const f of fonts) copyFileSync(join(fontSrc, f), join('dist/fonts', f));
copyFileSync('node_modules/@fontsource/courier-prime/LICENSE', 'dist/fonts/OFL.txt');
console.log('built dist/main.cjs + dist/renderer.mjs + dist/fonts');
