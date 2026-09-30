// Fountain -> Final Draft XML (FDX). Unprinted Fountain (notes, sections,
// synopses, boneyard, page breaks) is dropped.
import { normalizeMeta } from '../fountain/document.js';
import { parse } from '../fountain/parse.js';

const TYPE = {
  scene_heading: 'Scene Heading', action: 'Action', character: 'Character', parenthetical: 'Parenthetical',
  dialogue: 'Dialogue', transition: 'Transition', centered: 'Action', lyric: 'Action',
};
const UPPER = new Set(['scene_heading', 'character', 'transition']);
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' };
const esc = (s) => s.replace(/[&<>"]/g, (c) => ESC[c]);

function runs(text) {
  const state = { b: false, i: false, u: false };
  const out = [];
  let buf = '';
  const flush = () => {
    if (!buf) return;
    const style = [state.b && 'Bold', state.i && 'Italic', state.u && 'Underline'].filter(Boolean).join('+');
    out.push(style ? `<Text Style="${style}">${esc(buf)}</Text>` : `<Text>${esc(buf)}</Text>`);
    buf = '';
  };
  let last = 0;
  for (const m of text.matchAll(/\\([*_])|\*\*\*|\*\*|\*|_/g)) {
    buf += text.slice(last, m.index);
    last = m.index + m[0].length;
    if (m[1]) { buf += m[1]; continue; }
    flush();
    if (m[0] === '***') { state.b = !state.b; state.i = !state.i; } else if (m[0] === '**') state.b = !state.b;
    else if (m[0] === '*') state.i = !state.i;
    else state.u = !state.u;
  }
  buf += text.slice(last);
  flush();
  return out.join('') || '<Text></Text>';
}

function paragraph(el, indent = '    ') {
  const text = UPPER.has(el.type) ? el.text.toUpperCase() : el.text;
  const align = el.type === 'centered' ? ' Alignment="Center"' : '';
  return `${indent}<Paragraph Type="${TYPE[el.type]}"${align}>${runs(text)}</Paragraph>`;
}

export function toFdx(meta, body) {
  const m = normalizeMeta(meta);
  const els = parse(body).filter((e) => TYPE[e.type]);
  const out = [];
  for (let k = 0; k < els.length; k++) {
    const el = els[k];
    if (el.type === 'character' && el.dual === 'left') {
      const block = [el];
      let j = k + 1;
      while (j < els.length && (els[j].type === 'dialogue' || els[j].type === 'parenthetical' || (els[j].type === 'character' && els[j].dual === 'right' && !block.some((b) => b.dual === 'right')))) {
        block.push(els[j]);
        j++;
      }
      if (block.some((b) => b.dual === 'right')) {
        out.push('    <Paragraph>', '      <DualDialogue>', ...block.map((b) => paragraph(b, '        ')), '      </DualDialogue>', '    </Paragraph>');
        k = j - 1;
        continue;
      }
    }
    out.push(paragraph(el));
  }
  const tp = [
    m.title && `      <Paragraph Alignment="Center">${runs(m.title)}</Paragraph>`,
    m.credit && `      <Paragraph Alignment="Center">${runs(m.credit)}</Paragraph>`,
    m.author && `      <Paragraph Alignment="Center">${runs(m.author)}</Paragraph>`,
    m.source && `      <Paragraph Alignment="Center">${runs(m.source)}</Paragraph>`,
    ...[m.draft_date, ...m.contact.split('\n')].filter(Boolean).map((l) => `      <Paragraph Alignment="Left">${runs(l)}</Paragraph>`),
  ].filter(Boolean);
  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>',
    '<FinalDraft DocumentType="Script" Template="No" Version="5">',
    '  <Content>',
    ...out,
    '  </Content>',
    '  <TitlePage>',
    '    <Content>',
    ...tp,
    '    </Content>',
    '  </TitlePage>',
    '</FinalDraft>',
    '',
  ].join('\n');
}
