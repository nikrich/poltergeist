import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { FONT_FILES } from '../../render/pageHtml.js';
import { exportName, inlineFonts } from '../files.js';

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
});
