/**
 * Defence in depth for rendered Mermaid SVG (on top of mermaid's own
 * securityLevel 'strict'): clicking a diagram must never navigate the window
 * or run a handler. <foreignObject> is deliberately KEPT, since mermaid's HTML
 * labels live inside it; the rules below apply inside it too (ruling R7).
 */

const XLINK_NS = 'http://www.w3.org/1999/xlink';
const FORBIDDEN_TAGS = 'script, iframe, object, embed, form, input';

function isLinkAttr(name: string): boolean {
  return name === 'href' || name === 'xlink:href';
}

function sanitizeElement(el: Element): void {
  const isAnchor = el.localName.toLowerCase() === 'a';
  if (isAnchor) {
    el.removeAttributeNS(XLINK_NS, 'href');
    el.removeAttribute('xlink:href');
    el.removeAttribute('href');
    el.removeAttribute('target');
  }
  for (const attr of Array.from(el.attributes)) {
    const name = attr.name.toLowerCase();
    const value = attr.value.trim().toLowerCase();
    const drop =
      name.startsWith('on') ||
      value.startsWith('javascript:') ||
      (isLinkAttr(name) && !attr.value.trim().startsWith('#'));
    if (drop) el.removeAttributeNode(attr);
  }
}

function sanitizeSubtree(root: Element | DocumentFragment): void {
  for (const el of Array.from(root.querySelectorAll(FORBIDDEN_TAGS))) el.remove();
  for (const el of Array.from(root.querySelectorAll('*'))) sanitizeElement(el);
}

/** Mutates root's subtree (root included) in place. */
export function sanitizeDiagramDom(root: Element): void {
  sanitizeElement(root);
  sanitizeSubtree(root);
}

/**
 * Parses svg markup in an inert <template> and sanitises it while it is still
 * owned by the template's inert document, so nothing loads or runs before the
 * nodes are clean. The result is ready to insert into the live document.
 */
export function sanitizedDiagramFragment(svg: string): DocumentFragment {
  const template = document.createElement('template');
  template.innerHTML = svg;
  sanitizeSubtree(template.content);
  return template.content;
}

/** String form of sanitizedDiagramFragment. */
export function sanitizeDiagramSvg(svg: string): string {
  const template = document.createElement('template');
  template.content.append(sanitizedDiagramFragment(svg));
  return template.innerHTML;
}
