import { useState } from 'react';
import { useBacklinks } from '../lib/api/hooks';
import { Lucide } from './Lucide';

const WIKILINK_DISPLAY_RE = /!?\[\[([^\][|]+?)(?:\|([^\]]+))?\]\]/g;

/** Raw `[[path|Alias]]` markup → what a reader sees: the alias, else the basename. */
export function displaySnippet(snippet: string): string {
  return snippet.replace(
    WIKILINK_DISPLAY_RE,
    (_m, target: string, alias?: string) => alias ?? target.split('/').pop() ?? target,
  );
}

interface Props {
  /** Vault-relative `.md` path of the note being viewed. */
  path: string;
  onOpen: (path: string) => void;
  /** Controlled open state (A7 page byline). Omit both for the old behaviour. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function BacklinksPanel({ path, onOpen, open: openProp, onOpenChange }: Props) {
  const [ownOpen, setOwnOpen] = useState(true);
  const open = openProp ?? ownOpen;
  const setOpen = (next: boolean) => (onOpenChange ? onOpenChange(next) : setOwnOpen(next));
  const query = useBacklinks(path);
  const items = Array.isArray(query.data?.items) ? query.data.items : [];
  const indexing = query.data?.indexing === true;
  const settled = query.isSuccess && !indexing;

  return (
    <section aria-label="backlinks" className="flex-shrink-0 border-t border-hairline">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-4 py-2 font-mono text-10 uppercase tracking-wide text-ink-3 hover:text-ink-1"
      >
        <Lucide name={open ? 'chevron-down' : 'chevron-right'} size={11} />
        {`backlinks${settled ? ` · ${items.length}` : ''}`}
      </button>
      {open && (
        <div className="max-h-48 overflow-y-auto px-4 pb-3">
          {query.isLoading && <div className="text-11 text-ink-3">loading…</div>}
          {query.isError && (
            <div className="flex items-center gap-2 text-11 text-ink-3">
              backlinks unavailable
              <button type="button" onClick={() => void query.refetch()} className="underline">
                retry
              </button>
            </div>
          )}
          {indexing && <div className="text-11 text-ink-3">indexing vault…</div>}
          {settled && items.length === 0 && (
            <div className="text-11 text-ink-3">no backlinks yet</div>
          )}
          {settled && items.length > 0 && (
            <ul>
              {items.map((b) => (
                <li key={b.path}>
                  <button
                    type="button"
                    onClick={() => onOpen(b.path)}
                    className="w-full rounded-sm px-2 py-1 text-left hover:bg-fog/50"
                  >
                    <div className="flex items-center gap-2">
                      <span className="truncate text-12 text-ink-0">{b.title}</span>
                      {b.context && <span className="font-mono text-10 text-ink-3">{b.context}</span>}
                    </div>
                    {b.snippet && (
                      <div className="truncate text-11 text-ink-2">{displaySnippet(b.snippet)}</div>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
