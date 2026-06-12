import { describe, it, expect } from 'vitest';
import { wrapPrintableHtml } from '../pdf-export';

describe('wrapPrintableHtml', () => {
  it('wraps body HTML inside a full document skeleton', () => {
    const result = wrapPrintableHtml('My Doc', '<p>Hello</p>');
    expect(result).toContain('<!doctype html>');
    expect(result).toContain('<title>My Doc</title>');
    expect(result).toContain('<p>Hello</p>');
  });

  it('includes a <style> tag with print CSS', () => {
    const result = wrapPrintableHtml('T', '');
    expect(result).toContain('<style>');
    expect(result).toContain('font:');
  });

  it('escapes < and > in the title', () => {
    const result = wrapPrintableHtml('<script>bad</script>', '');
    expect(result).toContain('&lt;script&gt;bad&lt;/script&gt;');
    // The raw angle brackets must not appear inside the title element.
    expect(result).not.toContain('<title><script>');
  });

  it('escapes & in the title', () => {
    const result = wrapPrintableHtml('Cats & Dogs', '');
    expect(result).toContain('Cats &amp; Dogs');
  });

  it('escapes " in the title', () => {
    const result = wrapPrintableHtml('Say "hi"', '');
    expect(result).toContain('Say &quot;hi&quot;');
  });

  it('passes body HTML through unescaped', () => {
    // Body is trusted renderer HTML — it must not be double-escaped.
    const body = '<h1>Hello &amp; welcome</h1><p class="x">Test</p>';
    const result = wrapPrintableHtml('T', body);
    expect(result).toContain(body);
  });

  it('sets charset to utf-8', () => {
    const result = wrapPrintableHtml('T', '');
    expect(result).toContain('<meta charset="utf-8">');
  });
});
