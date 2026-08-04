import { readFileSync } from 'node:fs';
import { describe, it, expect } from 'vitest';

/**
 * Regression guard for the webcam/inline-image feature: the renderer CSP must
 * allow the custom `gbasset:` scheme in `img-src`, otherwise Chromium blocks
 * every vault-asset image (tree thumbnails AND inline photos) before the
 * protocol handler is ever reached — the image just shows as broken.
 *
 * Vitest runs with cwd = desktop/, so the HTML files are read by repo-relative
 * path.
 */
function imgSrc(htmlPath: string): string {
  const html = readFileSync(htmlPath, 'utf8');
  const m = html.match(/img-src ([^;]+);/);
  const directive = m?.[1];
  if (directive === undefined) throw new Error(`no img-src directive found in ${htmlPath}`);
  return directive;
}

describe('renderer CSP allows gbasset: images', () => {
  for (const html of ['src/renderer/index.html', 'src/renderer/overlay.html']) {
    it(`${html} img-src includes gbasset: (plus self + data:)`, () => {
      const src = imgSrc(html);
      expect(src).toContain("'self'");
      expect(src).toContain('data:');
      expect(src).toContain('gbasset:');
    });
  }
});
