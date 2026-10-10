import { useBacklinks } from '../../lib/api/hooks';
import { formatRelativeTime } from '../../lib/format';
import { Btn } from '../Btn';
import type { GuardHandle } from '../GuardedNoteEditor';
import { Lucide } from '../Lucide';
import { NoteHistoryButton } from '../NoteHistory';

interface Props {
  author: string;
  /** ISO timestamp; null hides the "updated" item. */
  updated: string | null;
  /** Vault-relative path of the page (history + backlinks). */
  path: string;
  guardRef: React.MutableRefObject<GuardHandle | null>;
  /** Opens the backlinks panel and brings it into view. */
  onShowBacklinks: () => void;
}

/**
 * Confluence-style byline under the page title (A7): who, when, then the
 * page's history and backlinks. Deliberately quiet (12px ink-2) so the title
 * stays the one bold element; items are spaced apart, never dot-joined.
 */
export function PageByline({ author, updated, path, guardRef, onShowBacklinks }: Props) {
  const backlinks = useBacklinks(path);
  const items = backlinks.data?.items;
  const count =
    backlinks.isSuccess && backlinks.data?.indexing !== true && Array.isArray(items)
      ? items.length
      : null;
  const initial = author.trim().charAt(0).toUpperCase() || '?';

  return (
    <div
      data-testid="page-byline"
      className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-12 text-ink-2"
    >
      <span className="flex min-w-0 items-center gap-2">
        <span
          aria-hidden
          className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-pill border border-hairline-2 bg-fog text-10 font-semibold leading-none text-ink-1"
        >
          {initial}
        </span>
        <span className="truncate font-medium text-ink-1">{author}</span>
      </span>
      {updated && (
        <time dateTime={updated} title={updated} className="tabular-nums">
          {`updated ${formatRelativeTime(updated)}`}
        </time>
      )}
      {/* History + backlinks stay as quiet as the byline text: the arbitrary
          child variants (0,1,1) out-specify Btn's ghost/sm utilities (0,1,0). */}
      <span className="ml-auto flex items-center gap-1 [&>button]:px-2 [&>button]:py-[3px] [&>button]:font-normal [&>button]:text-ink-2 [&>button:hover]:text-ink-0">
        <NoteHistoryButton key={path} path={path} guardRef={guardRef} />
        {count !== null && (
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="link-2" size={13} />}
            onClick={onShowBacklinks}
          >
            {count === 1 ? '1 backlink' : `${count} backlinks`}
          </Btn>
        )}
      </span>
    </div>
  );
}
