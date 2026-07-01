import { describe, it, expect } from 'vitest';
import { wrapPrintableHtml, isGeneratedDocPath } from '../pdf-export';

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

describe('isGeneratedDocPath', () => {
  it('accepts a generated-docs .html path', () => {
    expect(isGeneratedDocPath('20-contexts/generated-docs/20260701T120000-x.html')).toBe(true);
  });
  it('rejects paths outside generated-docs', () => {
    expect(isGeneratedDocPath('20-contexts/sanlam/notes/x.html')).toBe(false);
  });
  it('rejects non-.html', () => {
    expect(isGeneratedDocPath('20-contexts/generated-docs/x.md')).toBe(false);
  });
  it('rejects path traversal', () => {
    expect(isGeneratedDocPath('20-contexts/generated-docs/../../etc/x.html')).toBe(false);
  });
});
