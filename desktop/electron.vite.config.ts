import { defineConfig, externalizeDepsPlugin } from 'electron-vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { resolve } from 'node:path';
import { readFileSync } from 'node:fs';

// Single source of truth for the app version. Synced from package.json at
// build time and injected as `__APP_VERSION__` so the renderer doesn't have
// to maintain its own hardcoded string.
const APP_VERSION = JSON.parse(
  readFileSync(resolve(__dirname, 'package.json'), 'utf-8'),
).version as string;

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: { outDir: 'out/main' },
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: { outDir: 'out/preload' },
  },
  renderer: {
    root: resolve(__dirname, 'src/renderer'),
    plugins: [react(), tailwindcss()],
    define: {
      __APP_VERSION__: JSON.stringify(APP_VERSION),
    },
    // The packaged renderer loads via file:// — absolute URLs like /assets/...
    // resolve to the filesystem root. `./` makes Vite emit relative URLs for
    // bundled assets (CSS / JS / imported images). Runtime-constructed URLs
    // (img src=`assets/...`) must also avoid leading slashes; see the
    // connector icon paths in screens/connectors.tsx etc.
    base: './',
    build: {
      outDir: 'out/renderer',
      rollupOptions: {
        input: {
          index: resolve(__dirname, 'src/renderer/index.html'),
          overlay: resolve(__dirname, 'src/renderer/overlay.html'),
        },
      },
    },
  },
});
