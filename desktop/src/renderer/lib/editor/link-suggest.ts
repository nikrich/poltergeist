import type { Editor } from '@tiptap/core';
import { get } from '../api/client';
import type { SuggestItem, SuggestKind, SuggestResponse } from '../../../shared/api-types';

/** Spec: suggest endpoints that fail or exceed 300 ms show "no suggestions". */
export const SUGGEST_TIMEOUT_MS = 300;
export const SUGGEST_LIMIT = 20;

export interface SuggestResult {
  items: SuggestItem[];
  indexing: boolean;
}

const EMPTY: SuggestResult = { items: [], indexing: false };

/** Never rejects: a failure or timeout is an empty result, so typing never blocks. */
export async function fetchSuggestions(
  kind: SuggestKind,
  query: string,
  timeoutMs: number = SUGGEST_TIMEOUT_MS,
): Promise<SuggestResult> {
  const path = `/v1/vault/suggest?kind=${kind}&q=${encodeURIComponent(query)}&limit=${SUGGEST_LIMIT}`;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<SuggestResult>((resolve) => {
    timer = setTimeout(() => resolve(EMPTY), timeoutMs);
  });
  try {
    return await Promise.race([
      get<SuggestResponse>(path).then((r) => ({
        items: Array.isArray(r?.items) ? r.items : [],
        indexing: r?.indexing === true,
      })),
      timeout,
    ]);
  } catch {
    return EMPTY;
  } finally {
    clearTimeout(timer);
  }
}

/** Out-of-order responses would show results for an older query; every
 * superseded call answers with the newest request's result instead. */
export function createLatestFetcher(
  fetcher: (kind: SuggestKind, query: string) => Promise<SuggestResult> = fetchSuggestions,
): (kind: SuggestKind, query: string) => Promise<SuggestResult> {
  let seq = 0;
  let latest: Promise<SuggestResult> = Promise.resolve(EMPTY);
  return async (kind, query) => {
    const mine = ++seq;
    const pending = fetcher(kind, query);
    latest = pending;
    const result = await pending;
    return mine === seq ? result : latest;
  };
}

/** Vault path → wikilink target (no `.md`). */
export function noteTarget(path: string): string {
  return path.replace(/\.md$/i, '');
}

/** Wikilink target → note path the sidecar's GET /v1/notes accepts. */
export function notePathFromTarget(target: string): string {
  const bare = target.split('#')[0]!.trim();
  return /\.md$/i.test(bare) ? bare : `${bare}.md`;
}

function aliasText(label: string): string {
  return label.replace(/[[\]|]/g, ' ').replace(/\s+/g, ' ').trim();
}

/** Markdown inserted for a chosen suggestion (spec storage table). Inside a
 * GFM table the `|` of an alias would split the cell, so links go bare. */
export function linkTextFor(item: SuggestItem, opts: { inTable: boolean }): string {
  if (item.kind === 'tag') return `#${item.label}`;
  const target = noteTarget(item.path ?? item.label);
  if (opts.inTable) return `[[${target}]]`;
  const alias = aliasText(item.label);
  if (!alias) return `[[${target}]]`;
  return item.kind === 'person' ? `[[${target}|@${alias.replace(/^@/, '')}]]` : `[[${target}|${alias}]]`;
}

export function isInTable(editor: Editor): boolean {
  const { $from } = editor.state.selection;
  for (let depth = $from.depth; depth > 0; depth--) {
    const name = $from.node(depth).type.name;
    if (name === 'tableCell' || name === 'tableHeader') return true;
  }
  return false;
}
