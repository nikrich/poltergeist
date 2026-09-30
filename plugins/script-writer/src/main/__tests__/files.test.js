import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { FONT_FILES } from '../../render/pageHtml.js';
import { exportName, inlineFonts, withTimeout } from '../files.js';

describe('files', () => {
  it('builds safe export names', () => {
    expect(exportName('my/script:v2', 'pdf')).toBe('my-script-v2.pdf');
    expect(exportName('', 'fountain')).toBe('screenplay.fountain');
    expect(exportName('a.PDF', 'pdf')).toBe('a.PDF');
  });
  it('inlines font placeholders as data URLs and rejects unknown files', () => {
    const d = mkdtempSync(join(tmpdir(), 'sw-fonts-'));
    for (const f of FONT_FILES) writeFileSync(join(d, f), 'woff');
    const out = inlineFonts(`url("__FONT_BASE__${FONT_FILES[0]}")`, d);
    expect(out).toBe(`url("data:font/woff2;base64,${Buffer.from('woff').toString('base64')}")`);
    expect(() => inlineFonts('url("__FONT_BASE__../x.woff2")', d)).toThrow(/unknown font/);
  });
  it('withTimeout rejects with the given message when the work hangs', async () => {
    await expect(withTimeout(new Promise(() => {}), 10, 'PDF export timed out')).rejects.toThrow('PDF export timed out');
  });
  it('withTimeout passes through the result or error of work that settles in time', async () => {
    await expect(withTimeout(Promise.resolve(7), 1000, 'late')).resolves.toBe(7);
    await expect(withTimeout(Promise.reject(new Error('boom')), 1000, 'late')).rejects.toThrow('boom');
  });
});
