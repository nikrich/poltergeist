/**
 * A7 page title. The title is a line of the note body, never frontmatter:
 * B1's body save keeps frontmatter bytes exactly and there is no title
 * write path.
 *  - 'note': a leading ATX H1 (`# Title`) is the title.
 *  - 'jot':  the same, or a plain first line followed by a blank line or the
 *            end of the body (the line title_from_body() lists for jots).
 * `head` holds the title line and its surrounding blank lines byte for byte,
 * so a save that only changed the body never rewrites the title line.
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
const H1_RE = /^ {0,3}# +(.*?)(?: +#+)? *$/;
/** First-line shapes that are markdown blocks, not a title. */
const NOT_PLAIN = /^(?:#|[-*+](?:\s|$)|\d{1,9}[.)](?:\s|$)|>|`{3}|~{3}|!\[|\||<|(?:[-*_][ \t]*){3,}$|=+$)/;
/** Inline markup a plain textarea title cannot show. */
const INLINE_MARKUP = /\[\[|\]\(|`|\*\*|__/;
const PLAIN_MAX = 120;
const TITLE_MAX = 200;

function isPlainTitle(text: string): boolean {
  return (
    text !== '' && text.length <= PLAIN_MAX && !NOT_PLAIN.test(text) && !INLINE_MARKUP.test(text)
  );
}

const unescapeTitle = (s: string): string => s.replace(/\\(#+)$/, '$1');
/** A trailing ` #…` is an ATX closing sequence: escape it. */
const escapeH1 = (s: string): string => s.replace(/( )(#+)$/, '$1\\$2');

export function sanitizePageTitle(raw: string): string {
  return raw.replace(/\s+/g, ' ').trim().slice(0, TITLE_MAX);
}

export function splitPageTitle(body: string, rule: TitleRule): PageTitleSplit {
  const eol: '\n' | '\r\n' = body.includes('\r\n') ? '\r\n' : '\n';
  const none: PageTitleSplit = { title: '', kind: null, head: '', rest: body, eol };

  const lead = BLANK_RUN.exec(body)![0];
  const afterLead = body.slice(lead.length);
  const nl = afterLead.search(/\r?\n/);
  const line = nl === -1 ? afterLead : afterLead.slice(0, nl);
  const lineEol = nl === -1 ? '' : afterLead.startsWith('\r\n', nl) ? '\r\n' : '\n';
  const tail = afterLead.slice(line.length + lineEol.length);
  const blanks = BLANK_RUN.exec(tail)![0];
  const rest = tail.slice(blanks.length);
  const head = lead + line + lineEol + blanks;

  const h1 = H1_RE.exec(line);
  if (h1) {
    const title = unescapeTitle(h1[1]!.trim());
    return title === '' ? none : { title, kind: 'h1', head, rest, eol };
  }
  if (rule !== 'jot') return none;
  const text = line.trim();
  const endsBlock = lineEol === '' || blanks !== '' || rest.trim() === '';
  if (!endsBlock || !isPlainTitle(text)) return none;
  return { title: text, kind: 'plain', head, rest, eol };
}

export function joinPageTitle(split: PageTitleSplit, rest: string): string {
  if (split.kind === null) return rest;
  const { head, eol } = split;
  if (rest.trim() === '') return head;
  if (/\r?\n[ \t]*\r?\n$/.test(head)) return head + rest;
  // An H1 ends at its line ending; a plain line needs a blank line or it
  // merges into the first paragraph.
  if (split.kind === 'h1' && /\n$/.test(head)) return head + rest;
  return head.replace(/[ \t]*(?:\r?\n)?$/, '') + eol + eol + rest;
}

export function retitlePage(split: PageTitleSplit, raw: string): PageTitleSplit | null {
  const title = sanitizePageTitle(raw);
  if (title === '' || title === split.title) return null;
  const { eol } = split;
  if (split.kind === null) {
    return { title, kind: 'h1', head: `# ${escapeH1(title)}${eol}${eol}`, rest: split.rest, eol };
  }
  // Swap only the title line; keep the blank lines before and after it.
  const m = /^((?:[ \t]*\r?\n)*)([^\r\n]*)([\s\S]*)$/.exec(split.head)!;
  const plain = split.kind === 'plain' && isPlainTitle(title);
  const line = plain ? title : `# ${escapeH1(title)}`;
  return { title, kind: plain ? 'plain' : 'h1', head: m[1]! + line + m[3]!, rest: split.rest, eol };
}
