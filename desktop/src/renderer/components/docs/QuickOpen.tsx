import { useEffect, useState } from 'react';
import { useLibrarySearch } from '../../lib/api/hooks';
import { KindChip } from './KindChip';

interface Props {
  open: boolean;
  onClose: () => void;
  onPick: (docId: string) => void;
}

export function QuickOpen({ open, onClose, onPick }: Props) {
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const results = useLibrarySearch(q).data ?? [];

  useEffect(() => {
    if (!open) setQ('');
  }, [open]);
  useEffect(() => setActive(0), [q]);

  if (!open) return null;
  const pick = (i: number) => {
    const hit = results[i];
    if (!hit) return;
    onPick(hit.doc_id);
    onClose();
  };
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 pt-[14vh]" onMouseDown={onClose}>
      <div className="w-[520px] overflow-hidden rounded-xl border border-hairline-2 bg-vellum shadow-[0_24px_60px_rgba(0,0,0,.65)]" onMouseDown={(e) => e.stopPropagation()}>
        <input
          autoFocus
          value={q}
          placeholder="find a doc…"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
            if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
            if (e.key === 'Enter') pick(active);
            if (e.key === 'Escape') onClose();
          }}
          className="w-full border-b border-hairline bg-transparent px-4 py-3 text-14 text-ink-0 outline-none placeholder:text-ink-3"
        />
        <div className="max-h-[320px] overflow-y-auto py-1">
          {results.map((d, i) => (
            <button
              key={d.doc_id}
              type="button"
              onMouseEnter={() => setActive(i)}
              onClick={() => pick(i)}
              className={`flex w-full items-center gap-2.5 px-4 py-2 text-left text-[13.5px] ${i === active ? 'bg-neon-mist text-ink-0' : 'text-ink-1'}`}
            >
              <KindChip doc={d} />
              <span className="truncate">{d.title}</span>
              <span className={`ml-auto truncate font-mono text-[10.5px] ${i === active ? 'text-neon-ink' : 'text-ink-3'}`}>
                {[d.project ?? d.context, d.folder].filter(Boolean).join(' / ')}
              </span>
            </button>
          ))}
          {q && results.length === 0 && <div className="px-4 py-3 text-12 text-ink-3">no matching docs</div>}
        </div>
        <div className="flex gap-3.5 border-t border-hairline px-4 py-2 font-mono text-10 text-ink-3">
          <span>↑↓ navigate</span><span>↵ open</span><span>esc close</span>
        </div>
      </div>
    </div>
  );
}
