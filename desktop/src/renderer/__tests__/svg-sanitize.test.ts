import { describe, it, expect } from 'vitest';
import { sanitizeDiagramDom, sanitizeDiagramSvg } from '../lib/editor/svg-sanitize';
import { MALICIOUS_SVG, expectNoLinksOrHandlers } from './helpers/malicious-svg';

function parse(markup: string): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = markup;
  return host;
}

function expectSanitized(root: Element): void {
  expectNoLinksOrHandlers(root);
  expect(root.querySelector('script')).toBeNull();
  expect(root.querySelector('svg')).not.toBeNull();
  expect(root.querySelector('use')?.getAttribute('href')).toBe('#arrowhead');
  expect(root.querySelector('foreignObject')).not.toBeNull();
  expect(root.textContent).toContain('link in label');
  expect(root.textContent).toContain('node');
  expect(root.querySelector('rect[style]')?.getAttribute('style')).toBe('fill: red');
}

describe('sanitizeDiagramDom', () => {
  it('fixture really contains the attack vectors before sanitising', () => {
    const root = parse(MALICIOUS_SVG);
    expect(root.querySelector('script')).not.toBeNull();
    expect(root.querySelector('a')?.getAttributeNS('http://www.w3.org/1999/xlink', 'href')).toBe(
      'https://evil.example/x',
    );
    expect(root.querySelector('g[onclick]')).not.toBeNull();
    expect(root.querySelector('foreignObject a')?.getAttribute('href')).toBe('https://evil.example/md');
  });

  it('strips links, targets, handlers and scripts but keeps labels, foreignObject and fragment hrefs', () => {
    const root = parse(MALICIOUS_SVG);
    sanitizeDiagramDom(root);
    expectSanitized(root);
    expect(root.querySelectorAll('a')).toHaveLength(2); // <a> kept so labels stay visible
  });

  it('removes iframe, object, embed, form and input', () => {
    const root = parse(
      '<svg><foreignObject><div><iframe src="x"></iframe><object data="x"></object><embed src="x">' +
        '<form action="x"><input value="y"></form><span>ok</span></div></foreignObject></svg>',
    );
    sanitizeDiagramDom(root);
    for (const tag of ['iframe', 'object', 'embed', 'form', 'input']) {
      expect(root.querySelector(tag), tag).toBeNull();
    }
    expect(root.textContent).toContain('ok');
  });

  it('removes javascript: in any attribute and non-fragment hrefs on other elements', () => {
    const root = parse(
      '<svg><use href=" JavaScript:alert(1)"></use><image href="https://evil.example/i.png"></image>' +
        '<g data-x="javascript:void(0)" style="fill:blue"><text>t</text></g></svg>',
    );
    sanitizeDiagramDom(root);
    expect(root.querySelector('use')?.hasAttribute('href')).toBe(false);
    expect(root.querySelector('image')?.hasAttribute('href')).toBe(false);
    expect(root.querySelector('g')?.hasAttribute('data-x')).toBe(false);
    expect(root.querySelector('g')?.getAttribute('style')).toBe('fill:blue');
  });

  it('strips handlers on the root element itself', () => {
    const root = parse('<svg onload="alert(1)"><g></g></svg>');
    const svg = root.querySelector('svg')!;
    sanitizeDiagramDom(svg);
    expect(svg.hasAttribute('onload')).toBe(false);
  });
});

describe('sanitizeDiagramSvg', () => {
  it('returns markup that is clean after re-parsing', () => {
    const out = sanitizeDiagramSvg(MALICIOUS_SVG);
    expect(out).not.toMatch(/evil\.example|onclick|onmouseover|<script/i);
    expectSanitized(parse(out));
  });
});
