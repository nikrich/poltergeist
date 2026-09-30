// Page[] → absolutely positioned HTML. One renderer for the in-app page view
// and the PDF, so what you see is what prints.
import { normalizeMeta } from '../fountain/document.js';

export const FONT_PLACEHOLDER = '__FONT_BASE__';
export const FONT_FILES = [
  'courier-prime-latin-400-normal.woff2', 'courier-prime-latin-400-italic.woff2',
  'courier-prime-latin-700-normal.woff2', 'courier-prime-latin-700-italic.woff2',
];

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };
const esc = (s) => s.replace(/[&<>"]/g, (c) => ESC[c]);
const top = (y) => `${(1 + y / 6).toFixed(4)}in`;
const left = (x) => `${(1.5 + x / 10).toFixed(2)}in`;
const fresh = () => ({ b: false, i: false, u: false });

export function inlineHtml(text, state) {
  let html = '';
  let last = 0;
  const flush = (s) => {
    if (!s) return;
    const cls = ['b', 'i', 'u'].filter((k) => state[k]).join(' ');
    html += cls ? `<span class="${cls}">${esc(s)}</span>` : esc(s);
  };
  for (const m of text.matchAll(/\\([*_])|\*\*\*|\*\*|\*|_/g)) {
    flush(text.slice(last, m.index));
    last = m.index + m[0].length;
    if (m[1]) { flush(m[1]); continue; }
    if (m[0] === '***') { state.b = !state.b; state.i = !state.i; } else if (m[0] === '**') state.b = !state.b;
    else if (m[0] === '*') state.i = !state.i;
    else state.u = !state.u;
  }
  flush(text.slice(last));
  return html;
}

export function renderPage(page) {
  let html = '<div class="sw-page">';
  if (page.number > 1) html += `<div class="sw-ln sw-pn" style="top:0.5in;right:1in">${page.number}.</div>`;
  let state = fresh();
  let lastEl = null;
  for (const l of page.lines) {
    if (l.el !== lastEl || l.el === -1) { state = fresh(); lastEl = l.el; }
    const cls = `sw-ln sw-t-${l.type}${l.italic ? ' sw-italic' : ''}`;
    html += `<div class="${cls}" style="top:${top(l.y)};left:${left(l.x)}">${inlineHtml(l.text, state)}</div>`;
    if (l.sceneNumber) {
      const n = esc(l.sceneNumber);
      html += `<div class="sw-ln sw-sn" style="top:${top(l.y)};left:0.75in">${n}</div>`;
      html += `<div class="sw-ln sw-sn" style="top:${top(l.y)};left:7.6in">${n}</div>`;
    }
  }
  return `${html}</div>`;
}

export function renderTitlePage(meta) {
  const m = normalizeMeta(meta);
  if (!m.title.trim()) return '';
  let html = '<div class="sw-page sw-title-page">';
  const block = (y0, value, cls, pos) => value.split('\n').forEach((line, n) => {
    const style = pos === 'center' ? `top:${top(y0 + n)}` : `top:${top(y0 + n)};left:1.5in`;
    const clsAttr = cls ? ` ${cls}` : '';
    html += `<div class="sw-ln${clsAttr}" style="${style}">${esc(line)}</div>`;
  });
  block(18, m.title.toUpperCase(), 'sw-center sw-tp-title', 'center');
  if (m.credit) block(21, m.credit, 'sw-center', 'center');
  if (m.author) block(23, m.author, 'sw-center', 'center');
  if (m.source) block(26, m.source, 'sw-center', 'center');
  if (m.draft_date) block(46, m.draft_date, '', 'left');
  if (m.contact) block(48, m.contact, '', 'left');
  return `${html}</div>`;
}

export function pageCss(paper = 'letter') {
  const [w, h] = paper === 'a4' ? ['8.27in', '11.69in'] : ['8.5in', '11in'];
  return [
    `.sw-page{position:relative;width:${w};height:${h};background:#fff;color:#111;box-sizing:border-box;overflow:hidden;`,
    "font-family:'Courier Prime','Courier New',Courier,monospace;font-size:12pt}",
    `.sw-ln{position:absolute;white-space:pre;line-height:${(1 / 6).toFixed(4)}in}`,
    '.sw-t-scene_heading{font-weight:700}.sw-italic{font-style:italic}',
    '.sw-center{left:1.5in;width:6in;text-align:center}.sw-tp-title{font-weight:700;text-decoration:underline}',
    '.sw-page .b{font-weight:700}.sw-page .i{font-style:italic}.sw-page .u{text-decoration:underline}',
  ].join('');
}

export function fontFaceCss(base) {
  return FONT_FILES.map((f) => {
    const [, weight, style] = f.match(/-(\d{3})-(normal|italic)\.woff2$/);
    return `@font-face{font-family:'Courier Prime';font-weight:${weight};font-style:${style};src:url("${base}${f}") format("woff2")}`;
  }).join('');
}

export function documentHtml({ meta, pages, paper = 'letter', fontBase = FONT_PLACEHOLDER }) {
  const size = paper === 'a4' ? 'A4' : 'letter';
  const css = `${fontFaceCss(fontBase)}@page{size:${size};margin:0}html,body{margin:0;padding:0}${pageCss(paper)}`
    + '.sw-page{break-after:page}.sw-page:last-child{break-after:auto}';
  return `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head><body>${renderTitlePage(meta)}${pages.map(renderPage).join('')}</body></html>`;
}
