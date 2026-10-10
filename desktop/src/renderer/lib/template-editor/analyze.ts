/**
 * Read-only text analysis of a template file for the template editor:
 * where the frontmatter and the `prompts:` list are, which prompts the
 * template declares, whether a position is inside a ```query fence, and
 * what kind of completion fits at the cursor. Pure functions over the
 * document text; nothing here is evaluated.
 */

export interface PromptInfo {
  id: string;
  type: string;
}

export interface FrontmatterRange {
  /** Offset of the first character after the opening `---` line. */
  innerStart: number;
  /** Offset of the closing `---` line. */
  innerEnd: number;
  /** Offset of the first character after the closing `---` line. */
  bodyStart: number;
}

export type CursorContext =
  | { kind: 'variable'; from: number; prefix: string }
  | { kind: 'field'; from: number; prefix: string; ownerPath: string[] }
  | { kind: 'filter'; from: number; prefix: string }
  | { kind: 'prompt-type'; from: number; prefix: string }
  | { kind: 'query-key'; from: number; prefix: string }
  | { kind: 'query-value'; from: number; prefix: string; key: string };

const PROMPT_TYPES = 'person|text|date|choice|context|project';
const ID_RE = /(?:^|[\s,{])id:[ \t]*["']?([a-z][a-z0-9_]{0,31})\b/;
const TYPE_RE = new RegExp(`(?:^|[\\s,{])type:[ \\t]*["']?(${PROMPT_TYPES})\\b`);
const FENCE_OPEN_RE = /^ {0,3}(`{3,}|~{3,})[ \t]*([^\s`]*)/;
const FENCE_CLOSE_RE = /^ {0,3}(`{3,}|~{3,})[ \t]*$/;

function lineAt(text: string, pos: number): { start: number; end: number } {
  const start = text.lastIndexOf('\n', pos - 1) + 1;
  const nl = text.indexOf('\n', pos);
  return { start, end: nl < 0 ? text.length : nl };
}

export function frontmatterRange(text: string): FrontmatterRange | null {
  const first = text.startsWith('---\r\n') ? 5 : text.startsWith('---\n') ? 4 : -1;
  if (first < 0) return null;
  let pos = first;
  for (;;) {
    const nl = text.indexOf('\n', pos);
    const end = nl < 0 ? text.length : nl;
    if (/^-{3,}[ \t]*\r?$/.test(text.slice(pos, end))) {
      return { innerStart: first, innerEnd: pos, bodyStart: nl < 0 ? text.length : nl + 1 };
    }
    if (nl < 0) return null;
    pos = nl + 1;
  }
}

/** The `prompts:` key and its list, as offsets into `text`. */
export function promptsSection(text: string): { start: number; end: number } | null {
  const fm = frontmatterRange(text);
  if (!fm) return null;
  const inner = text.slice(fm.innerStart, fm.innerEnd);
  const m = /^([ \t]*)prompts:/m.exec(inner);
  if (!m) return null;
  const indent = m[1]!.length;
  const start = fm.innerStart + m.index;
  let pos = inner.indexOf('\n', m.index);
  while (pos >= 0 && pos + 1 < inner.length) {
    pos += 1;
    const nl = inner.indexOf('\n', pos);
    const line = inner.slice(pos, nl < 0 ? inner.length : nl).replace(/\r$/, '');
    const trimmed = line.trimStart();
    const lineIndent = line.length - trimmed.length;
    if (trimmed && !trimmed.startsWith('#') && lineIndent <= indent && !trimmed.startsWith('-')) {
      return { start, end: fm.innerStart + pos };
    }
    pos = nl;
  }
  return { start, end: fm.innerEnd };
}

/** The prompts the template declares, in order (block or flow YAML). */
export function extractPrompts(text: string): PromptInfo[] {
  const section = promptsSection(text);
  if (!section) return [];
  // A lone `{` opens a flow mapping; `{{` is a placeholder inside a string.
  const items = text.slice(section.start, section.end).split(/\n[ \t]*-[ \t]+|(?<!\{)\{(?!\{)/);
  const out: PromptInfo[] = [];
  const seen = new Set<string>();
  for (const item of items.slice(1)) {
    const id = ID_RE.exec(item)?.[1];
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push({ id, type: TYPE_RE.exec(item)?.[1] ?? 'text' });
  }
  return out;
}

/** True when `pos` is on a content line of a ```query fence in the body. */
export function inQueryFence(text: string, pos: number): boolean {
  const fm = frontmatterRange(text);
  let lineStart = fm ? fm.bodyStart : 0;
  if (pos < lineStart) return false;
  let open: { ch: string; len: number; query: boolean } | null = null;
  for (;;) {
    const nl = text.indexOf('\n', lineStart);
    const lineEnd = nl < 0 ? text.length : nl;
    const line = text.slice(lineStart, lineEnd).replace(/\r$/, '');
    const close = open ? FENCE_CLOSE_RE.exec(line) : null;
    const closes = !!open && !!close && close[1]![0] === open.ch && close[1]!.length >= open.len;
    if (pos <= lineEnd) return !!open && open.query && !closes;
    if (closes) {
      open = null;
    } else if (!open) {
      const m = FENCE_OPEN_RE.exec(line);
      if (m) open = { ch: m[1]![0]!, len: m[1]!.length, query: m[2]!.toLowerCase() === 'query' };
    }
    if (nl < 0) return false;
    lineStart = nl + 1;
  }
}

function placeholderContext(before: string, pos: number): CursorContext | null | undefined {
  const open = before.lastIndexOf('{{');
  if (open < 0 || before.indexOf('}}', open) >= 0) return undefined;
  const expr = before.slice(open + 2);
  const pipe = expr.lastIndexOf('|');
  if (pipe >= 0) {
    const last = expr.slice(pipe + 1);
    if (last.includes(':')) return null; // a filter argument: nothing to offer
    const prefix = last.trimStart();
    if (!/^[A-Za-z0-9_]*$/.test(prefix)) return null;
    return { kind: 'filter', from: pos - prefix.length, prefix };
  }
  const path = expr.trimStart();
  if (!/^[A-Za-z0-9_.]*$/.test(path)) return null;
  const parts = path.split('.');
  const prefix = parts.pop()!;
  if (parts.length === 0) return { kind: 'variable', from: pos - prefix.length, prefix };
  if (parts.some((p) => p === '')) return null;
  return { kind: 'field', from: pos - prefix.length, prefix, ownerPath: parts };
}

/** What to complete at `pos`, or null when nothing fits. */
export function cursorContext(text: string, pos: number): CursorContext | null {
  const { start } = lineAt(text, pos);
  const before = text.slice(start, pos);
  const inPlaceholder = placeholderContext(before, pos);
  if (inPlaceholder !== undefined) return inPlaceholder;
  const section = promptsSection(text);
  if (section && pos >= section.start && pos <= section.end) {
    const m = /^[ \t]*(?:-[ \t]+)?type:[ \t]*["']?([a-z]*)$/.exec(before);
    return m ? { kind: 'prompt-type', from: pos - m[1]!.length, prefix: m[1]! } : null;
  }
  if (!inQueryFence(text, pos)) return null;
  const key = /^[ \t]*([A-Za-z]*)$/.exec(before);
  if (key) return { kind: 'query-key', from: pos - key[1]!.length, prefix: key[1]! };
  const value = /^[ \t]*([A-Za-z]+)[ \t]*:[ \t]*["']?([^"'\n]*)$/.exec(before);
  if (value) {
    const prefix = value[2]!;
    return { kind: 'query-value', from: pos - prefix.length, prefix, key: value[1]!.toLowerCase() };
  }
  return null;
}
