import { useMemo } from 'react';
import { GraphCanvas } from './GraphCanvas';
import { OntologyNodePanel } from './OntologyNodePanel';
import { PanelEmpty } from './PanelEmpty';
import { PanelError } from './PanelError';
import { SkeletonRows } from './SkeletonRows';
import { layoutEgo } from '../lib/graph/layout';
import { useOntologyGraph } from '../lib/api/ontology-hooks';
import { useOntologyView } from '../stores/ontology-view';
import type { GraphKind } from '../../shared/api-types';

const NONE: ReadonlySet<GraphKind> = new Set();

const CHIP = 'rounded-sm border px-2 py-[2px] font-mono text-11';
const chip = (on: boolean) => `${CHIP} ${on ? 'border-neon/30 bg-neon/15 text-neon-ink' : 'border-hairline-2 text-ink-1'}`;

export function OntologyGraph({ project }: { project: string }) {
  const {
    focus, depth, selected, showRejected, showAllSources,
    setFocus, setSelected, setDepth, setShowRejected, setShowAllSources, setTab,
  } = useOntologyView();
  const graph = useOntologyGraph(project, focus, depth, { includeRejected: showRejected, allSources: showAllSources });
  const scene = useMemo(() => (graph.data ? layoutEgo(graph.data) : null), [graph.data]);

  if (graph.isError) return <PanelError message={String(graph.error)} onRetry={() => void graph.refetch()} />;
  if (!scene) return <SkeletonRows count={3} height={48} />;
  const noFacts = graph.data?.counts?.facts === 0 && !showAllSources;
  const empty = scene.nodes.length <= 1;

  return (
    <div className="flex flex-1 overflow-hidden">
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <div className="absolute right-4 top-3 z-10 flex gap-1">
        {([1, 2, 3] as const).map((d) => (
          <button key={d} type="button" onClick={() => setDepth(d)}
                  className={chip(d === depth)}>
            depth {d}
          </button>
        ))}
        <button type="button" aria-pressed={showRejected} onClick={() => setShowRejected(!showRejected)} className={chip(showRejected)}>
          show rejected
        </button>
        <button type="button" aria-pressed={showAllSources} onClick={() => setShowAllSources(!showAllSources)} className={chip(showAllSources)}>
          show all sources
        </button>
        {focus && (
          <button type="button" onClick={() => setFocus(null)} className={chip(false)}>
            project
          </button>
        )}
      </div>
      {graph.data?.truncated && (
        <div
          role="status"
          className="absolute left-4 top-3 z-10 rounded-pill border border-hairline bg-paper/70 px-3 py-[6px] font-mono text-11 text-ink-1 backdrop-blur-md"
        >
          {`showing the first ${graph.data.nodes.length} nodes — recentre to explore`}
        </div>
      )}
      {noFacts ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3">
          <p className="font-mono text-12 text-ink-1">No facts yet — run extraction from the Backlog</p>
          <button type="button" onClick={() => setTab('backlog')} className={chip(false)}>go to backlog</button>
        </div>
      ) : empty ? (
        <PanelEmpty icon="network" message="nothing ratified yet — ratify a binding to start" />
      ) : (
        <GraphCanvas
          scene={scene}
          hiddenKinds={NONE}
          ariaLabel="ontology graph"
          onRecenter={(node) => setSelected(node.path)}
          onOpen={(node) => setFocus(node.path)}
        />
      )}
    </div>
    {selected && <OntologyNodePanel uid={selected} />}
    </div>
  );
}
