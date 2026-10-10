import type { SuggestItem } from '../../shared/api-types';

interface Props {
  items: SuggestItem[];
  highlightedIndex: number;
  top: number;
  left: number;
  /** Shown as a muted row when there are no items; null renders nothing. */
  emptyText: string | null;
  onSelect: (item: SuggestItem) => void;
}

export function SuggestMenu({ items, highlightedIndex, top, left, emptyText, onSelect }: Props) {
  if (items.length === 0 && !emptyText) return null;

  return (
    <div
      role="listbox"
      aria-label="suggestions"
      style={{ position: 'absolute', top, left, zIndex: 9999 }}
      className="max-h-72 w-72 overflow-y-auto rounded border border-hairline bg-vellum shadow-md"
    >
      {items.length === 0 ? (
        <div className="px-3 py-1.5 font-mono text-11 text-ink-3">{emptyText}</div>
      ) : (
        items.map((item, i) => (
          <button
            key={`${item.kind}:${item.path ?? item.label}`}
            type="button"
            role="option"
            aria-selected={i === highlightedIndex}
            onMouseDown={(e) => {
              e.preventDefault();
              onSelect(item);
            }}
            className={`flex w-full flex-col px-3 py-1.5 text-left ${
              i === highlightedIndex ? 'bg-fog text-ink-0' : 'text-ink-1 hover:bg-fog/50'
            }`}
          >
            <span className="truncate text-12">{item.kind === 'tag' ? `#${item.label}` : item.label}</span>
            <span className="truncate font-mono text-10 text-ink-3">{item.detail}</span>
          </button>
        ))
      )}
    </div>
  );
}
