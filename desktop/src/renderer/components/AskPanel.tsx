import { useEffect, useRef, useState } from 'react';
import { useSearch } from '../lib/api/hooks';
import { useNoteView } from '../stores/note-view';
import { Lucide } from './Lucide';
import { SkeletonRows } from './SkeletonRows';
import { PanelError } from './PanelError';
import type { SearchHit } from '../../shared/api-types';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function AskPanel({ open, onClose }: Props) {
  const search = useSearch();
  const openNote = useNoteView((s) => s.open);
  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState('');

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = q.trim();
    if (!trimmed) return;
    search.mutate({ q: trimmed, limit: 10 });
  };

  const openHit = (hit: SearchHit) => {
    openNote(hit.path);
    onClose();
  };

  return (
    <div
      role="dialog"
      aria-label="ask the archive"
      className="fixed inset-0 z-50 flex items-start justify-center bg-[rgba(14,15,18,0.55)] backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="mt-[14vh] w-[640px] max-w-[92vw] rounded-r10 border border-hairline bg-vellum shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <form
          onSubmit={submit}
          className="flex items-center gap-2 border-b border-hairline px-4 py-3"
        >
          <Lucide name="search" size={14} color="var(--ink-2)" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="ask the archive…"
            className="flex-1 border-none bg-transparent text-14 text-ink-0 placeholder:text-ink-3 focus:outline-none"
          />
          <kbd className="rounded-xs bg-fog px-[6px] py-[2px] font-mono text-9 text-ink-2">
            esc
          </kbd>
        </form>

        <div className="max-h-[60vh] overflow-y-auto p-2">
          {search.isPending && <SkeletonRows count={4} />}
          {search.isError && (
            <PanelError
              message={
                search.error instanceof Error ? search.error.message : 'search failed'
              }
              onRetry={() => search.mutate({ q: q.trim(), limit: 10 })}
            />
          )}
          {search.data && search.data.items.length === 0 && !search.isPending && (
            <div className="px-3 py-6 text-center text-12 text-ink-2">
              no matches for &ldquo;{search.data.query}&rdquo;
            </div>
          )}
          {!search.data && !search.isPending && !search.isError && (
            <div className="px-3 py-6 text-center text-12 text-ink-3">
              press enter to search · esc to close
            </div>
          )}
          {search.data?.items.map((hit) => (
            <HitRow key={hit.path} hit={hit} onOpen={() => openHit(hit)} />
          ))}
        </div>
      </div>
    </div>
  );
}

function HitRow({ hit, onOpen }: { hit: SearchHit; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full flex-col gap-[2px] rounded-sm px-3 py-2 text-left hover:bg-paper"
    >
      <div className="flex items-baseline gap-2">
        <span className="flex-1 truncate text-13 text-ink-0">{hit.title}</span>
        <span className="font-mono text-10 text-ink-3">{hit.score.toFixed(2)}</span>
      </div>
      <div className="truncate font-mono text-10 text-ink-3">{hit.path}</div>
      {hit.snippet && (
        <div className="line-clamp-2 text-12 leading-[1.5] text-ink-2">{hit.snippet}</div>
      )}
    </button>
  );
}
