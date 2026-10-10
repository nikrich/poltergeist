/**
 * Callout grammar (spec §Markdown storage format). Obsidian/GitHub alert
 * syntax: `> [!kind][+-]? Optional title` followed by `> body` lines.
 * Only the six kinds below become callouts; anything else stays a plain
 * blockquote (ExtractCallout and other Obsidian types are untouched).
 */
export const CALLOUT_KINDS = ['info', 'note', 'tip', 'warning', 'error', 'success'] as const;
export type CalloutKind = (typeof CALLOUT_KINDS)[number];
export type CalloutFoldable = 'none' | 'open' | 'closed';

export interface CalloutAttrs {
  kind: CalloutKind;
  /** Raw source text after the marker; never parsed as inline markdown. */
  title: string | null;
  foldable: CalloutFoldable;
}

const HEADER_RE = /^\[!(info|note|tip|warning|error|success)\]([+-]?)(?:[ \t]+(.*))?$/;

export function parseCalloutHeader(line: string): CalloutAttrs | null {
  const m = HEADER_RE.exec(line);
  if (!m) return null;
  const title = (m[3] ?? '').trim();
  return {
    kind: m[1] as CalloutKind,
    foldable: m[2] === '-' ? 'closed' : m[2] === '+' ? 'open' : 'none',
    title: title === '' ? null : title,
  };
}

export function calloutHeader(attrs: CalloutAttrs): string {
  const fold = attrs.foldable === 'closed' ? '-' : attrs.foldable === 'open' ? '+' : '';
  return `[!${attrs.kind}]${fold}${attrs.title ? ` ${attrs.title}` : ''}`;
}

export function sanitizeCalloutTitle(raw: string): string | null {
  const t = raw.replace(/\s+/g, ' ').trim();
  return t === '' ? null : t;
}

export function isCalloutKind(v: unknown): v is CalloutKind {
  return typeof v === 'string' && (CALLOUT_KINDS as readonly string[]).includes(v);
}

export function isFoldable(v: unknown): v is CalloutFoldable {
  return v === 'none' || v === 'open' || v === 'closed';
}

// Minimal structural types for the markdown-it surface we touch (avoids a
// direct dependency on markdown-it's type package paths).
interface MdToken {
  type: string;
  content: string;
  attrSet(name: string, value: string): void;
}
interface MdCoreState {
  tokens: MdToken[];
}
export interface MdLike {
  core: {
    ruler: {
      after(afterName: string, ruleName: string, fn: (state: MdCoreState) => void): void;
    };
  };
}

/**
 * Runs after block parsing and before inline parsing, so we can read the raw
 * first line of the blockquote's first paragraph. Matching blockquotes get
 * data-* attrs (rendered by markdown-it's default renderer and picked up by
 * the callout node's parseHTML); the header line is removed from the body.
 */
export function calloutCoreRule(state: MdCoreState): void {
  const tokens = state.tokens;
  for (let i = 0; i + 2 < tokens.length; i++) {
    const open = tokens[i]!;
    const pOpen = tokens[i + 1]!;
    const inline = tokens[i + 2]!;
    if (open.type !== 'blockquote_open' || pOpen.type !== 'paragraph_open' || inline.type !== 'inline') {
      continue;
    }
    const nl = inline.content.indexOf('\n');
    const firstLine = nl === -1 ? inline.content : inline.content.slice(0, nl);
    const attrs = parseCalloutHeader(firstLine);
    if (!attrs) continue;
    open.attrSet('data-callout', attrs.kind);
    open.attrSet('data-foldable', attrs.foldable);
    if (attrs.title) open.attrSet('data-title', attrs.title);
    const rest = nl === -1 ? '' : inline.content.slice(nl + 1);
    if (rest.trim() === '') {
      tokens.splice(i + 1, 3); // drop paragraph_open, inline, paragraph_close
    } else {
      inline.content = rest;
    }
  }
}

// tiptap-markdown calls parse.setup on EVERY parse with the same markdown-it
// instance — install the rule once per instance.
const installed = new WeakSet<object>();

export function installCalloutRule(md: MdLike): void {
  if (installed.has(md)) return;
  installed.add(md);
  md.core.ruler.after('block', 'gb_callout', calloutCoreRule);
}
