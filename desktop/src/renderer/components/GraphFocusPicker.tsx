import { useEffect, useMemo, useState } from 'react';
import type { SuggestItem } from '../../shared/api-types';
import { createLatestFetcher } from '../lib/editor/link-suggest';

export const PICKER_LIMIT = 8;

interface Props {
  /** Title of the current focus, shown as the placeholder. */
  current: string | null;
  onPick: (path: string) => void;
}

export function GraphFocusPicker({ current, onPick }: Props) {
  const [q, setQ] = useState('');
  const [items, setItems] = useState<SuggestItem[]>([]);
  const fetchLatest = useMemo(() => createLatestFetcher(), []);

  useEffect(() => {
    const query = q.trim();
    if (!query) {
      setItems([]);
      return;
    }
    let live = true;
    void fetchLatest('page', query).then((r) => {
      if (live) setItems(r.items.filter((i) => i.path !== null).slice(0, PICKER_LIMIT));
    });
    return () => {
      live = false;
    };
  }, [q, fetchLatest]);

  const pick = (path: string) => {
    setQ('');
    setItems([]);
    onPick(path);
  };

  return (
    <div className="relative w-[280px]">
      <input
        aria-label="centre on page"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && items[0]?.path) pick(items[0].path);
          if (e.key === 'Escape') setQ('');
        }}
        placeholder={current ? `centred on ${current}` : 'centre on a page…'}
        className="w-full rounded-r6 border border-hairline bg-vellum px-3 py-[6px] text-12 text-ink-0 outline-none placeholder:text-ink-3 focus:border-hairline-3"
      />
      {items.length > 0 && (
        <ul
          aria-label="matching pages"
          className="absolute left-0 right-0 top-full z-30 mt-1 max-h-72 overflow-y-auto rounded-md border border-hairline-2 bg-paper p-1 shadow-float"
        >
          {items.map((item) => (
            <li key={item.path!}>
              <button
                type="button"
                onClick={() => pick(item.path!)}
                className="flex w-full flex-col items-start rounded-sm px-2 py-1 text-left hover:bg-vellum"
              >
                <span className="w-full truncate text-12 text-ink-0">{item.label}</span>
                <span className="w-full truncate font-mono text-10 text-ink-3">{item.detail}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
