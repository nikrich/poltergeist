import { build } from 'esbuild';
import { resolve } from 'node:path';

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
  // The bundled app components (desktop/src/renderer/components) are built by
  // Vite in the app; under esbuild we must supply Vite's env flag and React's
  // NODE_ENV ourselves.
  define: {
    'import.meta.env.DEV': 'false',
    'process.env.NODE_ENV': '"production"',
  },
  // The bundled desktop components would otherwise resolve react/lucide from
  // desktop/node_modules while our code resolves the plugin's copies — two
  // React instances make every hook crash. Pin everything to ONE copy.
  alias: {
    react: resolve('node_modules/react'),
    'react-dom': resolve('node_modules/react-dom'),
    'lucide-react': resolve('node_modules/lucide-react'),
  },
});
console.log('built dist/main.cjs + dist/renderer.mjs');
