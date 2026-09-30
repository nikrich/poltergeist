// Final Draft XML (FDX) -> Fountain + title meta. Uses the renderer's DOMParser.
import { DEFAULT_META, normalizeMeta } from '../fountain/document.js';
import { applyType } from '../editor/flow.js';

const FROM = {
  'Scene Heading': 'scene_heading', Action: 'action', Character: 'character', Parenthetical: 'parenthetical',
  Dialogue: 'dialogue', Transition: 'transition', Shot: 'scene_heading', General: 'action',
};
const NOT_FDX = 'Not a Final Draft (.fdx) file';
const kids = (node, tag) => [...node.children].filter((c) => c.tagName === tag);

function styled(t) {
  const style = t.getAttribute('Style') ?? '';
  const raw = t.textContent.replace(/([*_])/g, '\\$1');
  if (!raw) return '';
  let s = raw;
  if (/Bold/.test(style) && /Italic/.test(style)) s = `***${s}***`;
  else if (/Bold/.test(style)) s = `**${s}**`;
  else if (/Italic/.test(style)) s = `*${s}*`;
  if (/Underline/.test(style)) s = `_${s}_`;
  return s;
}
const paraText = (p) => kids(p, 'Text').map(styled).join('');
const paraPlain = (p) => kids(p, 'Text').map((t) => t.textContent).join('').trim();

export function fromFdx(xml, parser = new DOMParser()) {
  let doc;
  try { doc = parser.parseFromString(String(xml), 'application/xml'); } catch { throw new Error(NOT_FDX); }
  const root = doc?.documentElement;
  if (!root || root.tagName !== 'FinalDraft' || doc.getElementsByTagName('parsererror').length) throw new Error(NOT_FDX);
  const content = kids(root, 'Content')[0];
  const out = [];

  const emit = (p, dualRight) => {
    const type = FROM[p.getAttribute('Type')] ?? 'action';
    const text = paraText(p).trim();
    if (!text) return;
    let line = type === 'action' && p.getAttribute('Alignment') === 'Center' ? `>${text}<` : applyType(text, type);
    if (type === 'character' && dualRight) line += ' ^';
    if ((type === 'dialogue' || type === 'parenthetical') && out.length) out.push(line);
    else { if (out.length) out.push(''); out.push(line); }
  };

  for (const p of content ? kids(content, 'Paragraph') : []) {
    const dual = kids(p, 'DualDialogue')[0];
    if (!dual) { emit(p, false); continue; }
    let cues = 0;
    for (const q of kids(dual, 'Paragraph')) {
      const isCue = q.getAttribute('Type') === 'Character';
      if (isCue) cues++;
      emit(q, isCue && cues === 2);
    }
  }

  const meta = { ...DEFAULT_META };
  const tp = kids(root, 'TitlePage')[0];
  if (tp) {
    const lines = [...tp.getElementsByTagName('Paragraph')].map(paraPlain).filter(Boolean);
    if (lines[0]) meta.title = lines[0];
  }
  return { meta: normalizeMeta(meta), body: `${out.join('\n')}\n` };
}
