import type { TitleRule } from './editor/page-title';

type Frontmatter = Record<string, unknown> | null | undefined;

const text = (v: unknown): string | null =>
  typeof v === 'string' && v.trim() !== '' ? v.trim() : null;

/** Frontmatter `source` values written by the user (jots, chat summaries). */
const OWN_SOURCES = new Set(['manual', 'chat-summary']);

/** Ancestors shown above the page title (the page itself is the title). */
export function pageBreadcrumb(path: string, fm: Frontmatter): string[] {
  const dirs = path.split('/').filter((s) => s !== '' && s !== '.');
  dirs.pop();
  const context = text(fm?.context) ?? (dirs[0] === '20-contexts' ? (dirs[1] ?? null) : null);
  if (context) {
    const project = text(fm?.project);
    return project ? [context, project] : [context];
  }
  if (dirs[0] === '00-inbox') return ['inbox'];
  return dirs
    .map((d) => d.replace(/^\d{2}-/, ''))
    .filter((d) => d !== '')
    .slice(-3);
}

export function pageAuthor(fm: Frontmatter): string {
  const author = text(fm?.author);
  if (author) return author;
  const source = text(fm?.source);
  return source === null || OWN_SOURCES.has(source) ? 'you' : source;
}

/** First of updated → created → ingestedAt that parses as a date (a free-text
 * value like "tbd" would render "updated Invalid Date"). */
export function pageUpdated(fm: Frontmatter): string | null {
  for (const key of ['updated', 'created', 'ingestedAt'] as const) {
    const v = text(fm?.[key]);
    if (v !== null && !Number.isNaN(Date.parse(v))) return v;
  }
  return null;
}

/** Jots (and chat summaries) list their first line as the title. */
export function titleRuleFor(fm: Frontmatter): TitleRule {
  const source = text(fm?.source);
  return source !== null && OWN_SOURCES.has(source) ? 'jot' : 'note';
}
