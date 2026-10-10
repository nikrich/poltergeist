import { hoverTooltip, type Tooltip } from '@codemirror/view';
import type { TemplateFunctionSpec, TemplateRegistry } from '../../../shared/api-types';
import { extractPrompts, inQueryFence, promptsSection } from './analyze';
import { specInfo, valueTypeOf, type TemplateEditorData } from './completions';

export interface HoverHit {
  from: number;
  to: number;
  title: string;
  info: string;
}

/** Two quirks of C1's tokenizer, shown under every placeholder hover. */
export const PLACEHOLDER_SYNTAX_NOTE =
  "note: `{{{x}}` stays literal text, and a quoted filter argument can't contain `}}`.";

const WORD = /[A-Za-z0-9_]/;

function hit(from: number, to: number, title: string, spec: TemplateFunctionSpec): HoverHit {
  return { from, to, title, info: specInfo(spec) };
}

/** Split a placeholder expression on `|` outside double quotes; returns each
 * segment's start offset within `expr`. */
function segments(expr: string): { start: number; text: string }[] {
  const out: { start: number; text: string }[] = [];
  let start = 0;
  let quoted = false;
  for (let i = 0; i < expr.length; i += 1) {
    const ch = expr[i];
    if (ch === '\\' && quoted) i += 1;
    else if (ch === '"') quoted = !quoted;
    else if (ch === '|' && !quoted) {
      out.push({ start, text: expr.slice(start, i) });
      start = i + 1;
    }
  }
  out.push({ start, text: expr.slice(start) });
  return out;
}

function placeholderHit(
  text: string,
  wordFrom: number,
  wordTo: number,
  lineStart: number,
  lineEnd: number,
  reg: TemplateRegistry,
): HoverHit | null | undefined {
  const open = text.lastIndexOf('{{', wordFrom);
  if (open < lineStart || text.slice(open, wordFrom).includes('}}')) return undefined;
  const close = text.indexOf('}}', wordTo);
  if (close < 0 || close > lineEnd) return undefined;
  const expr = text.slice(open + 2, close);
  const rel = wordFrom - (open + 2);
  const word = text.slice(wordFrom, wordTo);
  const segs = segments(expr);
  const seg = [...segs].reverse().find((s) => s.start <= rel);
  if (!seg) return null;
  if (seg === segs[0]) {
    const names = seg.text.trim().split('.');
    const lead = seg.text.length - seg.text.trimStart().length;
    let offset = seg.start + lead;
    for (let i = 0; i < names.length; i += 1) {
      const name = names[i]!;
      if (rel === offset && word === name) {
        const prompts = extractPrompts(text);
        if (i === 0) {
          const prompt = prompts.find((p) => p.id === name);
          if (prompt) {
            const typeSpec = reg.promptTypes.find((t) => t.name === prompt.type);
            return {
              from: wordFrom,
              to: wordTo,
              title: `${name} — prompt (${prompt.type})`,
              info: typeSpec ? specInfo(typeSpec) : 'A prompt of this template.',
            };
          }
          const spec = reg.variables.find((v) => v.name === name);
          return spec ? hit(wordFrom, wordTo, `${name}: ${spec.type}`, spec) : null;
        }
        const owner = valueTypeOf(names.slice(0, i), prompts, reg);
        const spec = reg.fields.find((f) => f.owner === owner && f.name === name);
        return spec
          ? hit(wordFrom, wordTo, `${names.slice(0, i + 1).join('.')}: ${spec.type}`, spec)
          : null;
      }
      offset += name.length + 1;
    }
    return null;
  }
  const filterName = seg.text.split(':')[0]!;
  const lead = filterName.length - filterName.trimStart().length;
  if (rel !== seg.start + lead || word !== filterName.trim()) return null;
  const spec = reg.filters.find((f) => f.name === word);
  return spec ? hit(wordFrom, wordTo, `| ${word}`, spec) : null;
}

/** The registry entry under `pos`: a placeholder name, field or filter, a
 * prompt `type:` value, or a ```query key. */
export function hoverAt(text: string, pos: number, reg: TemplateRegistry): HoverHit | null {
  let wordFrom = pos;
  let wordTo = pos;
  while (wordFrom > 0 && WORD.test(text[wordFrom - 1]!)) wordFrom -= 1;
  while (wordTo < text.length && WORD.test(text[wordTo]!)) wordTo += 1;
  if (wordFrom === wordTo) return null;
  const word = text.slice(wordFrom, wordTo);
  const lineStart = text.lastIndexOf('\n', wordFrom - 1) + 1;
  const nl = text.indexOf('\n', wordTo);
  const lineEnd = nl < 0 ? text.length : nl;

  const inPlaceholder = placeholderHit(text, wordFrom, wordTo, lineStart, lineEnd, reg);
  if (inPlaceholder)
    return { ...inPlaceholder, info: `${inPlaceholder.info}\n\n${PLACEHOLDER_SYNTAX_NOTE}` };
  if (inPlaceholder === null) return null;

  const before = text.slice(lineStart, wordFrom);
  const section = promptsSection(text);
  if (section && wordFrom >= section.start && wordFrom <= section.end) {
    if (/^[ \t]*(?:-[ \t]+)?type:[ \t]*["']?$/.test(before)) {
      const spec = reg.promptTypes.find((t) => t.name === word);
      return spec ? hit(wordFrom, wordTo, `type: ${word}`, spec) : null;
    }
    return null;
  }
  if (inQueryFence(text, wordFrom) && /^[ \t]*$/.test(before) && text[wordTo] !== undefined) {
    if (!/^[ \t]*:/.test(text.slice(wordTo, lineEnd))) return null;
    const spec = (reg.queryKeys ?? []).find((k) => k.name === word.toLowerCase());
    return spec ? hit(wordFrom, wordTo, `${spec.name}:`, spec) : null;
  }
  return null;
}

/** Tooltip DOM built with textContent only: registry and template text are
 * never parsed as markup. */
export function hoverDom(h: HoverHit): HTMLElement {
  const dom = document.createElement('div');
  dom.className = 'gb-template-hover max-w-[360px] px-3 py-2 text-12';
  const title = document.createElement('div');
  title.className = 'font-mono text-11 text-ink-0';
  title.textContent = h.title;
  const info = document.createElement('div');
  info.className = 'mt-1 whitespace-pre-wrap text-ink-1';
  info.textContent = h.info;
  dom.append(title, info);
  return dom;
}

export function templateHover(getData: () => TemplateEditorData) {
  return hoverTooltip((view, pos): Tooltip | null => {
    const reg = getData().registry;
    if (!reg) return null;
    const h = hoverAt(view.state.doc.toString(), pos, reg);
    if (!h) return null;
    return { pos: h.from, end: h.to, above: true, create: () => ({ dom: hoverDom(h) }) };
  });
}
