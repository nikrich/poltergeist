import { useMemo, useState } from 'react';
import type { JotListItem } from '../../shared/api-types';
import { Lucide } from './Lucide';

interface Props {
  items: JotListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

interface ContextGroup {
  /** project slug → month → items */
  projects: Record<string, Record<string, JotListItem[]>>;
  /** month → items (project-less, original behavior) */
  months: Record<string, JotListItem[]>;
}

function groupItems(items: JotListItem[]): Record<string, ContextGroup> {
  const tree: Record<string, ContextGroup> = {};
  for (const item of items) {
    const ctx =
      item.routingStatus === 'manual_review'
        ? 'unrouted'
        : item.routingStatus === 'pending'
          ? 'inbox (pending)'
          : item.context ?? 'unrouted';
    const month = (item.created || '').slice(0, 7) || 'unknown';
    if (!tree[ctx]) tree[ctx] = { projects: {}, months: {} };
    const ctxGroup = tree[ctx]!;
    if (item.project) {
      if (!ctxGroup.projects[item.project]) ctxGroup.projects[item.project] = {};
      const projMonths = ctxGroup.projects[item.project]!;
      if (!projMonths[month]) projMonths[month] = [];
      projMonths[month]!.push(item);
    } else {
      if (!ctxGroup.months[month]) ctxGroup.months[month] = [];
      ctxGroup.months[month]!.push(item);
    }
  }
  return tree;
}

interface MonthListProps {
  ctx: string;
  byMonth: Record<string, JotListItem[]>;
  collapsed: Record<string, boolean>;
  toggle: (key: string) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  indent?: string;
}

function MonthList({ ctx, byMonth, collapsed, toggle, selectedId, onSelect, indent = 'ml-3' }: MonthListProps) {
  return (
    <>
      {Object.entries(byMonth)
        .sort(([a], [b]) => b.localeCompare(a))
        .map(([month, leaves]) => {
          const monthKey = `m:${ctx}:${month}`;
          const monthOpen = !collapsed[monthKey];
          return (
            <div key={month} className={indent}>
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
                        className={`flex items-center gap-1.5 rounded-sm px-2 py-[3px] text-left ${
                          selectedId === leaf.id
                            ? 'bg-neon/12 text-ink-0'
                            : 'text-ink-1 hover:bg-vellum'
                        }`}
                      >
                        {leaf.thumbnail && (
                          <img
                            src={window.gb.assets.toUrl(leaf.thumbnail)}
                            alt=""
                            className="h-7 w-7 shrink-0 rounded-sm object-cover"
                          />
                        )}
                        <span className="truncate">{leaf.title}</span>
                      </button>
                    ))}
                </div>
              )}
            </div>
          );
        })}
    </>
  );
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
        .map(([ctx, group]) => {
          const ctxKey = `ctx:${ctx}`;
          const open = !collapsed[ctxKey];
          const sortedProjects = Object.keys(group.projects).sort((a, b) => a.localeCompare(b));
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
              {open && (
                <>
                  {/* Project nodes (alphabetical) above loose months */}
                  {sortedProjects.map((slug) => {
                    const projKey = `proj:${ctx}:${slug}`;
                    const projOpen = !collapsed[projKey];
                    return (
                      <div key={slug} className="ml-3">
                        <button
                          type="button"
                          onClick={() => toggle(projKey)}
                          className="flex w-full items-center gap-1 px-1 py-1 text-ink-2 hover:bg-vellum"
                        >
                          <Lucide
                            name={projOpen ? 'chevron-down' : 'chevron-right'}
                            size={11}
                          />
                          <Lucide name="folder" size={11} className="opacity-60" />
                          <span className="font-mono">{slug}</span>
                        </button>
                        {projOpen && (
                          <MonthList
                            ctx={`${ctx}:${slug}`}
                            byMonth={group.projects[slug]!}
                            collapsed={collapsed}
                            toggle={toggle}
                            selectedId={selectedId}
                            onSelect={onSelect}
                            indent="ml-3"
                          />
                        )}
                      </div>
                    );
                  })}

                  {/* Loose months (project-less jots) */}
                  <MonthList
                    ctx={ctx}
                    byMonth={group.months}
                    collapsed={collapsed}
                    toggle={toggle}
                    selectedId={selectedId}
                    onSelect={onSelect}
                  />
                </>
              )}
            </div>
          );
        })}
    </div>
  );
}
