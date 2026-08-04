import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Mirror the renderer's build-time __APP_VERSION__ injection so tests that
// import `lib/version` don't blow up with "ReferenceError: __APP_VERSION__
// is not defined". See electron.vite.config.ts.
const APP_VERSION = JSON.parse(
  readFileSync(resolve(__dirname, 'package.json'), 'utf-8'),
).version as string;

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(APP_VERSION),
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/renderer/test/setup.ts'],
    globals: true,
    include: ['src/renderer/**/*.test.{ts,tsx}', 'src/main/**/*.test.ts'],
  },
});
