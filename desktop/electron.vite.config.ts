import { defineConfig, externalizeDepsPlugin } from 'electron-vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { resolve } from 'node:path';

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
    // The packaged renderer loads via file:// — absolute URLs like /assets/...
    // resolve to the filesystem root. `./` makes Vite emit relative URLs for
    // bundled assets (CSS / JS / imported images). Runtime-constructed URLs
    // (img src=`assets/...`) must also avoid leading slashes; see the
    // connector icon paths in screens/connectors.tsx etc.
    base: './',
    build: {
      outDir: 'out/renderer',
      rollupOptions: { input: resolve(__dirname, 'src/renderer/index.html') },
    },
  },
});
