import { describe, it, expect } from 'vitest';
import { sanitizeDiagramDom, sanitizeDiagramSvg, sanitizedDiagramFragment } from '../lib/editor/svg-sanitize';

const SVG_NS = 'http://www.w3.org/2000/svg';
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

  it('removes SMIL animation elements that could re-add a link', () => {
    const root = parse(
      '<svg><a><set attributeName="href" to="https://evil.example/s"></set>' +
        '<animate attributeName="href" values="x;javascript:alert(1)"></animate>' +
        '<animateMotion dur="1s"></animateMotion><animateTransform attributeName="transform"></animateTransform>' +
        '<discard></discard><text>x</text></a></svg>',
    );
    sanitizeDiagramDom(root);
    const left = Array.from(root.querySelectorAll('*')).map((el) => el.localName.toLowerCase());
    for (const tag of ['set', 'animate', 'animatemotion', 'animatetransform', 'discard']) {
      expect(left, tag).not.toContain(tag);
    }
    expect(root.textContent).toContain('x');
    expectNoLinksOrHandlers(root);
  });

  it('removes meta refresh, base and link inside foreignObject', () => {
    const root = parse(
      '<svg><foreignObject><div><meta http-equiv="refresh" content="0;url=https://evil.example">' +
        '<base href="https://evil.example/"><link rel="stylesheet" href="https://evil.example/c.css">' +
        '<span>label</span></div></foreignObject></svg>',
    );
    sanitizeDiagramDom(root);
    for (const tag of ['meta', 'base', 'link']) expect(root.querySelector(tag), tag).toBeNull();
    expect(root.textContent).toContain('label');
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

  it('keeps the SVG namespace through the template path', () => {
    const host = document.createElement('div');
    host.append(sanitizedDiagramFragment(MALICIOUS_SVG));
    expect(host.querySelector('svg')?.namespaceURI).toBe(SVG_NS);
    expect(host.querySelector('foreignObject')?.namespaceURI).toBe(SVG_NS);
    expectSanitized(host);
  });
});
