import { Lucide } from '../Lucide';
import { Pill } from '../Pill';
import { KIND_ICON, dayLabel, groupByDay, latestRev } from './kinds';
import type { ArtefactSummary } from '../../../shared/design-types';

interface Props {
  items: ArtefactSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

/** Artefacts grouped by day, newest first. */
export function ArtefactList({ items, selectedId, onSelect }: Props) {
  return (
    <ul aria-label="Artefacts" className="m-0 flex list-none flex-col gap-3 p-0">
      {groupByDay(items).map((g) => (
        <li key={g.day} className="flex flex-col gap-[2px]">
          <h4 className="m-0 px-2 pb-1 font-mono text-10 font-medium uppercase tracking-eyebrow-loose text-ink-2">
            {dayLabel(g.day)}
          </h4>
          {g.items.map((a) => (
            <ArtefactRow
              key={a.id}
              a={a}
              active={a.id === selectedId}
              onClick={() => onSelect(a.id)}
            />
          ))}
        </li>
      ))}
    </ul>
  );
}

function ArtefactRow({ a, active, onClick }: { a: ArtefactSummary; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-current={active ? 'true' : undefined}
      onClick={onClick}
      className={`flex w-full cursor-pointer items-start gap-[10px] rounded-sm px-2 py-[8px] text-left transition-colors duration-[120ms] ${
        active ? 'bg-neon/12' : 'hover:bg-vellum'
      }`}
    >
      <Lucide
        name={KIND_ICON[a.kind]}
        size={14}
        color={active ? 'var(--neon-glyph)' : 'var(--ink-2)'}
        className="mt-[2px]"
      />
      <span className="flex min-w-0 flex-1 flex-col gap-[2px] leading-[1.3]">
        <span className="truncate text-13 text-ink-0">{a.title}</span>
        {a.meeting && <span className="truncate text-11 text-ink-2">{a.meeting}</span>}
        {a.codebase && (
          <span className="truncate font-mono text-10 text-ink-3">
            {a.codebase.name} · {a.codebase.branch}
          </span>
        )}
        {a.codebase?.missing && (
          <span>
            <Pill tone="oxblood">worktree missing</Pill>
          </span>
        )}
      </span>
      <span className="whitespace-nowrap font-mono text-10 text-ink-3">rev {latestRev(a)}</span>
    </button>
  );
}
