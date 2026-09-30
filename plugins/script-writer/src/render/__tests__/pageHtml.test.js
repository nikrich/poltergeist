import { describe, expect, it } from 'vitest';
import { parse } from '../../fountain/parse.js';
import { paginate } from '../../paginate/paginate.js';
import { documentHtml, FONT_FILES, fontFaceCss, inlineHtml, renderPage, renderTitlePage } from '../pageHtml.js';

const fresh = () => ({ b: false, i: false, u: false });

describe('inlineHtml', () => {
  it('escapes HTML and renders emphasis as classed spans', () => {
    expect(inlineHtml('a <b> & **bold** *it* _u_ \\*x', fresh()))
      .toBe('a &lt;b&gt; &amp; <span class="b">bold</span> <span class="i">it</span> <span class="u">u</span> *x');
  });
  it('carries emphasis state across lines of one element', () => {
    const s = fresh();
    expect(inlineHtml('*start', s)).toBe('<span class="i">start</span>');
    expect(inlineHtml('end* now', s)).toBe('<span class="i">end</span> now');
  });
});

describe('renderPage', () => {
  it('positions lines in inches from the page edge and numbers pages from 2', () => {
    const pages = paginate(parse('INT. A - DAY #4#\n\nGo.\n\n===\n\nMore.'));
    const p1 = renderPage(pages[0]);
    expect(p1).toContain('class="sw-ln sw-t-scene_heading" style="top:1.0000in;left:1.50in"');
    expect(p1).toContain('class="sw-ln sw-sn" style="top:1.0000in;left:0.75in">4</div>');
    expect(p1).not.toContain('sw-pn');
    expect(renderPage(pages[1])).toContain('<div class="sw-ln sw-pn" style="top:0.5in;right:1in">2.</div>');
  });
});

describe('title page + document', () => {
  it('renders nothing without a title and escapes values', () => {
    expect(renderTitlePage({ title: '' })).toBe('');
    expect(renderTitlePage({ title: 'A <B>', author: 'Me' })).toContain('A &lt;B&gt;');
  });
  it('builds a full printable document with font faces', () => {
    const html = documentHtml({ meta: { title: 'X' }, pages: paginate(parse('Go.')), paper: 'a4', fontBase: '__FONT_BASE__' });
    expect(html.startsWith('<!doctype html>')).toBe(true);
    expect(html).toContain('@page{size:A4;margin:0}');
    for (const f of FONT_FILES) expect(html).toContain(`__FONT_BASE__${f}`);
    expect(fontFaceCss('B/')).toContain("font-family:'Courier Prime'");
  });
});
