import type { SlashItem } from '../lib/editor/slash';

interface Props {
  items: SlashItem[];
  highlightedIndex: number;
  top: number;
  left: number;
  onSelect: (item: SlashItem) => void;
}

export function SlashMenu({ items, highlightedIndex, top, left, onSelect }: Props) {
  if (items.length === 0) return null;

  return (
    <div
      style={{ position: 'absolute', top, left, zIndex: 9999 }}
      className="w-44 overflow-hidden rounded border border-hairline bg-vellum shadow-md"
    >
      {items.map((item, i) => (
        <button
          key={item.key}
          type="button"
          onMouseDown={(e) => {
            e.preventDefault();
            onSelect(item);
          }}
          className={`flex w-full items-center px-3 py-1.5 text-left font-mono text-11 ${
            i === highlightedIndex
              ? 'bg-fog text-ink-0'
              : 'text-ink-2 hover:bg-fog/50'
          }`}
        >
          {item.title}
        </button>
      ))}
    </div>
  );
}
