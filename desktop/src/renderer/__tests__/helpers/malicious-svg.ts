import { expect } from 'vitest';

const XLINK = 'http://www.w3.org/1999/xlink';

/** Crafted SVG mimicking mermaid output with every link/handler vector S1 strips. */
export const MALICIOUS_SVG = [
  '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" data-testid="evil-svg">',
  '<script>alert(1)</script>',
  '<a xlink:href="https://evil.example/x" href="https://evil.example/y" target="_blank"><g><text>node</text></g></a>',
  '<g onclick="alert(1)" onmouseover="x()"><rect width="10" height="10"></rect></g>',
  '<foreignObject width="100" height="20"><div><span><a href="https://evil.example/md">link in label</a></span></div></foreignObject>',
  '<use href="#arrowhead"></use>',
  '<rect style="fill: red" width="5" height="5"></rect>',
  '</svg>',
].join('');

/** Asserts no link/target/on* attribute survives under root (fragment hrefs on <use> allowed). */
export function expectNoLinksOrHandlers(root: Element): void {
  for (const el of Array.from(root.querySelectorAll('*'))) {
    const fragmentUse = el.tagName.toLowerCase() === 'use' && (el.getAttribute('href') ?? '').startsWith('#');
    if (!fragmentUse) {
      expect(el.getAttribute('href'), `${el.tagName} href`).toBeNull();
    }
    expect(el.getAttribute('xlink:href'), `${el.tagName} xlink:href`).toBeNull();
    expect(el.getAttributeNS(XLINK, 'href'), `${el.tagName} xlink ns href`).toBeNull();
    expect(el.getAttribute('target'), `${el.tagName} target`).toBeNull();
    for (const attr of Array.from(el.attributes)) {
      expect(attr.name.toLowerCase().startsWith('on'), `${el.tagName} ${attr.name}`).toBe(false);
    }
  }
}
