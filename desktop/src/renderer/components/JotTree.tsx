import { useMemo, useState } from 'react';
import type { JotListItem } from '../../shared/api-types';
import { Lucide } from './Lucide';

interface Props {
  items: JotListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

type Tree = Record<string, Record<string, JotListItem[]>>;

function groupItems(items: JotListItem[]): Tree {
  const tree: Tree = {};
  for (const item of items) {
    const ctx =
      item.routingStatus === 'manual_review'
        ? 'unrouted'
        : item.routingStatus === 'pending'
          ? 'inbox (pending)'
          : item.context ?? 'unrouted';
    const month = (item.created || '').slice(0, 7) || 'unknown';
    tree[ctx] ??= {};
    tree[ctx][month] ??= [];
    tree[ctx][month].push(item);
  }
  return tree;
}

export function JotTree({ items, selectedId, onSelect }: Props) {
  const tree = useMemo(() => groupItems(items), [items]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  function toggle(key: string) {
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  return (
    <div className="flex flex-col gap-1 overflow-y-auto px-2 py-2 text-12">
      {Object.entries(tree)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([ctx, byMonth]) => {
          const ctxKey = `ctx:${ctx}`;
          const open = !collapsed[ctxKey];
          return (
            <div key={ctx}>
              <button
                type="button"
                onClick={() => toggle(ctxKey)}
                className="flex w-full items-center gap-1 px-1 py-1 text-ink-1 hover:bg-vellum"
              >
                <Lucide name={open ? 'chevron-down' : 'chevron-right'} size={12} />
                <span className="font-mono">{ctx}</span>
              </button>
              {open &&
                Object.entries(byMonth)
                  .sort(([a], [b]) => b.localeCompare(a))
                  .map(([month, leaves]) => {
                    const monthKey = `m:${ctx}:${month}`;
                    const monthOpen = !collapsed[monthKey];
                    return (
                      <div key={month} className="ml-3">
                        <button
                          type="button"
                          onClick={() => toggle(monthKey)}
                          className="flex w-full items-center gap-1 px-1 py-1 text-ink-2 hover:bg-vellum"
                        >
                          <Lucide
                            name={monthOpen ? 'chevron-down' : 'chevron-right'}
                            size={11}
                          />
                          <span className="font-mono">{month}</span>
                        </button>
                        {monthOpen && (
                          <div className="ml-4 flex flex-col">
                            {leaves
                              .slice()
                              .sort((a, b) => b.created.localeCompare(a.created))
                              .map((leaf) => (
                                <button
                                  key={leaf.id}
                                  type="button"
                                  onClick={() => onSelect(leaf.id)}
                                  className={`truncate rounded-sm px-2 py-[3px] text-left ${
                                    selectedId === leaf.id
                                      ? 'bg-neon/12 text-ink-0'
                                      : 'text-ink-1 hover:bg-vellum'
                                  }`}
                                >
                                  {leaf.title}
                                </button>
                              ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
            </div>
          );
        })}
    </div>
  );
}
