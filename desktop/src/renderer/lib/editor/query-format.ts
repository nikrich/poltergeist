import type { VaultQueryRow } from '../../../shared/api-types';
import { noteTarget } from './link-suggest';

const CLOSED = new Set(['done', 'closed']);

/** Same rule as the sidecar's `status: open`: done/closed are closed, anything else (or none) is open. */
export function isClosedStatus(status: string | null): boolean {
  return CLOSED.has((status ?? '').toLowerCase());
}

function linkLabel(title: string): string {
  return title.replace(/[[\]|]/g, ' ').replace(/\s+/g, ' ').trim();
}

/** One frozen row: a GFM task item holding a titled wikilink. */
export function frozenItem(row: VaultQueryRow): string {
  const target = noteTarget(row.path);
  const label = linkLabel(row.title);
  const link = label && label !== target ? `[[${target}|${label}]]` : `[[${target}]]`;
  return `- [${isClosedStatus(row.status) ? 'x' : ' '}] ${link}`;
}

/** Markdown that replaces a ```query``` block on Freeze. */
export function freezeMarkdown(rows: VaultQueryRow[]): string {
  if (rows.length === 0) return 'no matching notes';
  return rows.map(frozenItem).join('\n');
}
