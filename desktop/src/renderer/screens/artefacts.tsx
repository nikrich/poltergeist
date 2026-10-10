import { useMemo, useState } from 'react';
import { TopBar } from '../components/TopBar';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';
import { SkeletonRows } from '../components/SkeletonRows';
import { ArtefactList } from '../components/artefacts/ArtefactList';
import { ArtefactDetailPane } from '../components/artefacts/ArtefactDetailPane';
import { useArtefacts } from '../lib/api/hooks';
import type { ArtefactKind } from '../../shared/design-types';

const KIND_FILTERS: { id: ArtefactKind | 'all'; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'prototype', label: 'Prototypes' },
  { id: 'worktree', label: 'Worktrees' },
  { id: 'board', label: 'Boards' },
];

const selectClass =
  'max-w-[160px] cursor-pointer truncate rounded-sm border border-hairline-2 bg-paper px-2 py-[3px] font-mono text-11 text-ink-0';

/** What live design sessions produced — prototypes, worktrees of existing
 *  apps and boards — each linked to the meeting it came from. */
export function ArtefactsScreen() {
  const artefacts = useArtefacts();
  const [kind, setKind] = useState<ArtefactKind | 'all'>('all');
  const [context, setContext] = useState('');
  const [selected, setSelected] = useState<string | null>(null);

  const all = useMemo(() => artefacts.data ?? [], [artefacts.data]);
  const contexts = useMemo(() => [...new Set(all.map((a) => a.context))].sort(), [all]);
  const shown = all.filter((a) => (kind === 'all' || a.kind === kind) && (!context || a.context === context));
  // Keep the selection while it is visible; otherwise show the newest.
  const current = shown.find((a) => a.id === selected)?.id ?? shown[0]?.id ?? null;

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <TopBar title="artefacts" subtitle={artefacts.data ? `${all.length} in vault` : '…'} />

      {artefacts.isLoading && <SkeletonRows count={5} />}
      {artefacts.isError && (
        <PanelError
          message={artefacts.error instanceof Error ? artefacts.error.message : 'failed to load artefacts'}
          onRetry={() => artefacts.refetch()}
        />
      )}
      {artefacts.data && all.length === 0 && (
        <PanelEmpty
          icon="layers"
          message={'No artefacts yet — start a recording and say “let\'s kick off a frontend prototype”.'}
        />
      )}

      {all.length > 0 && (
        <div className="flex min-h-0 flex-1">
          <aside className="flex w-[300px] flex-shrink-0 flex-col border-r border-hairline">
            <div className="flex flex-wrap items-center gap-2 border-b border-hairline px-3 py-3">
              <div className="flex items-center gap-[2px]">
                {KIND_FILTERS.map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    aria-pressed={kind === f.id}
                    onClick={() => setKind(f.id)}
                    className={`cursor-pointer rounded-sm px-2 py-[2px] font-mono text-11 ${
                      kind === f.id ? 'bg-neon/15 text-neon-ink' : 'text-ink-2 hover:text-ink-0'
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <select
                aria-label="Context"
                value={context}
                onChange={(e) => setContext(e.target.value)}
                className={selectClass}
              >
                <option value="">All contexts</option>
                {contexts.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex-1 overflow-y-auto px-2 py-3">
              {shown.length === 0 ? (
                <PanelEmpty icon="filter" message="nothing matches these filters" />
              ) : (
                <ArtefactList items={shown} selectedId={current} onSelect={setSelected} />
              )}
            </div>
          </aside>
          <main className="flex min-w-0 flex-1 flex-col overflow-y-auto px-6 py-5">
            {current && <ArtefactDetailPane key={current} id={current} />}
          </main>
        </div>
      )}
    </div>
  );
}
