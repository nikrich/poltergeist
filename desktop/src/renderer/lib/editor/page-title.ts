/**
 * A7 page title. The title is a line of the note body, never frontmatter:
 * B1's body save keeps frontmatter bytes exactly and there is no title
 * write path.
 *  - 'note': a leading ATX H1 (`# Title`) is the title.
 *  - 'jot':  the same, or a plain first line followed by a blank line or the
 *            end of the body (the line title_from_body() lists for jots).
 * `head` holds the title line and its surrounding blank lines byte for byte,
 * so a save that only changed the body never rewrites the title line.
 *
 * Runs on every body the editor opens (synced and imported notes included),
 * so every regex here is anchored with no overlapping quantifiers, and the
 * trailing-run scans are plain loops: parsing stays linear in the input.
 */
export type TitleRule = 'jot' | 'note';

export interface PageTitleSplit {
  /** Display title; '' when the body owns none. */
  title: string;
  /** How the body holds the title; null when it holds none. */
  kind: 'h1' | 'plain' | null;
  /** Raw text before `rest`: leading blank lines, the title line, its line
   * ending and the blank lines after it. '' when kind is null. */
  head: string;
  /** What the editor shows and edits. */
  rest: string;
  /** Line ending used when a head is rebuilt. */
  eol: '\n' | '\r\n';
}

const BLANK_RUN = /^(?:[ \t]*\r?\n)*/;
const H1_OPEN = /^ {0,3}# +/;
/** 4+ columns of indent: an indented code block, not a title. */
const CODE_INDENT = /^(?: {0,3}\t| {4})/;
/** First-line shapes that are markdown blocks, not a title. */
const NOT_PLAIN = /^(?:#|[-*+](?:\s|$)|\d{1,9}[.)](?:\s|$)|>|`{3}|~{3}|!\[|\||<|(?:[-*_][ \t]*){3,}$|=+$)/;
/** Inline markup a plain textarea title cannot show. */
const INLINE_MARKUP = /\[\[|\]\(|`|\*\*|__/;
const PLAIN_MAX = 120;
const TITLE_MAX = 200;
/** A longer first line is never a title; capping it bounds all the work. */
const LINE_SCAN_MAX = 2_000;

function isPlainTitle(text: string): boolean {
  return (
    text !== '' && text.length <= PLAIN_MAX && !NOT_PLAIN.test(text) && !INLINE_MARKUP.test(text)
  );
}

/** Index where the run of `ch` that ends `s` starts (s.length when none). */
function trailingRunStart(s: string, ch: string): number {
  let i = s.length;
  while (i > 0 && s[i - 1] === ch) i--;
  return i;
}

/** Index where the run of spaces/tabs that ends `s` starts, at or before `end`. */
function trailingBlankStart(s: string, end = s.length): number {
  let i = end;
  while (i > 0 && (s[i - 1] === ' ' || s[i - 1] === '\t')) i--;
  return i;
}

/** Length of `s` without one trailing line ending (if any). */
function withoutEol(s: string): number {
  if (!s.endsWith('\n')) return s.length;
  return s.length - (s.endsWith('\r\n') ? 2 : 1);
}

/** True when `s` ends with a line ending followed by a blank line. */
function endsWithBlankLine(s: string): boolean {
  if (!s.endsWith('\n')) return false;
  const i = trailingBlankStart(s, withoutEol(s));
  return i > 0 && s[i - 1] === '\n';
}

/** Leading blank lines, then the first line and its own line ending. */
function firstLine(s: string): { lead: string; line: string; lineEol: '' | '\n' | '\r\n' } {
  const lead = BLANK_RUN.exec(s)![0];
  const after = s.slice(lead.length);
  const nl = after.indexOf('\n');
  if (nl === -1) return { lead, line: after, lineEol: '' };
  const cr = nl > 0 && after[nl - 1] === '\r';
  return { lead, line: after.slice(0, cr ? nl - 1 : nl), lineEol: cr ? '\r\n' : '\n' };
}

/** H1 content after `# `, or null when the line is no H1. '' = empty heading. */
function parseH1(line: string): string | null {
  const open = H1_OPEN.exec(line);
  if (!open) return null;
  // `.` in the old pattern never crossed these: such a line is no H1.
  if (/[\r\u2028\u2029]/.test(line)) return null;
  let text = line.slice(open[0].length);
  text = text.slice(0, trailingBlankStart(text));
  const run = trailingRunStart(text, '#');
  if (run < text.length) {
    // A closing sequence follows a space or tab; one right after the
    // opening's spaces leaves an empty heading (`# #`).
    if (run === 0) return '';
    if (text[run - 1] === ' ' || text[run - 1] === '\t') text = text.slice(0, run);
  }
  text = text.trim();
  // `\#…` at the end is an escaped (literal) trailing `#` run.
  const lit = trailingRunStart(text, '#');
  if (lit < text.length && text[lit - 1] === '\\') text = text.slice(0, lit - 1) + text.slice(lit);
  return text;
}

/** Escape a trailing `#` run that would otherwise read back differently: one
 * after a space or a backslash, or a title that is only `#`s. */
function escapeH1(title: string): string {
  const run = trailingRunStart(title, '#');
  if (run === title.length) return title;
  const before = title[run - 1];
  if (run === 0 || before === ' ' || before === '\\') return `${title.slice(0, run)}\\${title.slice(run)}`;
  return title;
}

export function sanitizePageTitle(raw: string): string {
  const collapsed = raw.replace(/\s+/g, ' ').trim();
  // Cap by code points so a surrogate pair is never cut in half.
  return Array.from(collapsed).slice(0, TITLE_MAX).join('').trimEnd();
}

export function splitPageTitle(body: string, rule: TitleRule): PageTitleSplit {
  const eol: '\n' | '\r\n' = body.includes('\r\n') ? '\r\n' : '\n';
  const none: PageTitleSplit = { title: '', kind: null, head: '', rest: body, eol };

  const { lead, line, lineEol } = firstLine(body);
  if (line.length > LINE_SCAN_MAX) return none;
  const tail = body.slice(lead.length + line.length + lineEol.length);
  const blanks = BLANK_RUN.exec(tail)![0];
  const rest = tail.slice(blanks.length);
  const head = lead + line + lineEol + blanks;

  const h1 = parseH1(line);
  if (h1 !== null) return h1 === '' ? none : { title: h1, kind: 'h1', head, rest, eol };
  if (rule !== 'jot' || CODE_INDENT.test(line)) return none;
  const text = line.trim();
  const endsBlock = lineEol === '' || blanks !== '' || rest.trim() === '';
  if (!endsBlock || !isPlainTitle(text)) return none;
  return { title: text, kind: 'plain', head, rest, eol };
}

export function joinPageTitle(split: PageTitleSplit, rest: string): string {
  if (split.kind === null) return rest;
  const { head, eol } = split;
  if (rest.trim() === '') return head + rest;
  if (endsWithBlankLine(head)) return head + rest;
  // An H1 ends at its line ending; a plain line needs a blank line or it
  // merges into the first paragraph.
  if (split.kind === 'h1' && head.endsWith('\n')) return head + rest;
  return head.slice(0, trailingBlankStart(head, withoutEol(head))) + eol + eol + rest;
}

export function retitlePage(split: PageTitleSplit, raw: string): PageTitleSplit | null {
  const title = sanitizePageTitle(raw);
  if (title === '' || title === split.title) return null;
  const { eol } = split;
  if (split.kind === null) {
    return { title, kind: 'h1', head: `# ${escapeH1(title)}${eol}${eol}`, rest: split.rest, eol };
  }
  // Swap only the title line; keep the blank lines before and after it.
  const { lead, line: old } = firstLine(split.head);
  const plain = split.kind === 'plain' && isPlainTitle(title);
  const line = plain ? title : `# ${escapeH1(title)}`;
  const head = lead + line + split.head.slice(lead.length + old.length);
  return { title, kind: plain ? 'plain' : 'h1', head, rest: split.rest, eol };
}
