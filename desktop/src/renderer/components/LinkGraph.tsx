import { useMemo, type ReactNode } from 'react';

import type { NoteKind } from '../../shared/api-types';
import { ApiError } from '../lib/api/client';
import { useEgoGraph, useVaultGraph } from '../lib/api/hooks';
import { GHOST_COLOR, KIND_COLORS, KIND_LABELS, NOTE_KINDS } from '../lib/graph/kinds';
import { layoutEgo, sceneFromVaultGraph, type Scene, type SceneNode } from '../lib/graph/layout';
import { useGraphView, type GraphDepth } from '../stores/graph-view';
import { useNoteView } from '../stores/note-view';
import { toast } from '../stores/toast';
import { Ghost } from './Ghost';
import { GraphCanvas } from './GraphCanvas';
import { GraphFocusPicker } from './GraphFocusPicker';
import { Lucide } from './Lucide';
import { PanelError } from './PanelError';

/** Mirrors EGO_NODE_CAP in ghostbrain/api/repo/ego_graph.py (notice copy only). */
export const EGO_NODE_CAP = 300;

const chip = (on: boolean) =>
  `flex items-center gap-[6px] rounded-pill border px-3 py-[5px] font-mono text-11 transition-colors ${
    on
      ? 'border-hairline-2 bg-paper/80 text-ink-0'
      : 'border-hairline bg-paper/50 text-ink-3 line-through'
  }`;

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center text-13 text-ink-2">
      {children}
    </div>
  );
}

export function LinkGraph() {
  const focus = useGraphView((s) => s.focus);
  const back = useGraphView((s) => s.back);
  const depth = useGraphView((s) => s.depth);
  const wholeVault = useGraphView((s) => s.wholeVault);
  const hiddenKinds = useGraphView((s) => s.hiddenKinds);
  const recenter = useGraphView((s) => s.recenter);
  const goBack = useGraphView((s) => s.goBack);
  const setDepth = useGraphView((s) => s.setDepth);
  const setWholeVault = useGraphView((s) => s.setWholeVault);
  const toggleKind = useGraphView((s) => s.toggleKind);
  const openNote = useNoteView((s) => s.open);

  const ego = useEgoGraph(wholeVault ? null : focus, depth);
  const vault = useVaultGraph({ enabled: wholeVault });
  const hidden = useMemo(() => new Set<NoteKind>(hiddenKinds), [hiddenKinds]);

  const scene = useMemo<Scene | null>(() => {
    if (wholeVault) return vault.data ? sceneFromVaultGraph(vault.data, focus) : null;
    const data = ego.data;
    if (!data || data.indexing || data.nodes.length === 0) return null;
    return layoutEgo(data);
  }, [wholeVault, vault.data, ego.data, focus]);

  const onRecenter = (node: SceneNode) => recenter(node.path);
  const onOpen = (node: SceneNode) => {
    if (node.ghost) toast.info(`“${node.title}” isn't written yet`);
    else openNote(node.path);
  };

  const focusNode = scene && scene.focus >= 0 ? scene.nodes[scene.focus] : undefined;
  const focusTitle = focusNode?.title ?? (focus ? (focus.split('/').pop() ?? focus) : null);
  const status = wholeVault
    ? { isError: vault.isError, error: vault.error, refetch: () => void vault.refetch() }
    : { isError: ego.isError, error: ego.error, refetch: () => void ego.refetch() };

  let body: ReactNode;
  if (!wholeVault && focus === null) {
    body = (
      <Centered>
        <Lucide name="network" size={28} color="var(--ink-2)" />
        <p className="m-0 max-w-[360px]">
          pick a page to centre the graph on — or open a note and choose “show in graph”
        </p>
      </Centered>
    );
  } else if (status.isError) {
    const notFound = status.error instanceof ApiError && status.error.status === 404;
    const message = notFound
      ? 'that page is not in the vault any more'
      : status.error instanceof Error
        ? status.error.message
        : 'failed to load the graph';
    body = (
      <Centered>
        <PanelError message={message} onRetry={status.refetch} />
      </Centered>
    );
  } else if (!wholeVault && ego.data?.indexing) {
    body = (
      <Centered>
        <Ghost size={40} floating />
        <p className="m-0">indexing vault…</p>
      </Centered>
    );
  } else if (wholeVault && vault.data && vault.data.nodes.length === 0) {
    body = (
      <Centered>
        <p className="m-0">no notes under 20-contexts yet</p>
      </Centered>
    );
  } else if (scene === null) {
    body = (
      <Centered>
        <Ghost size={48} floating />
      </Centered>
    );
  } else {
    body = <GraphCanvas scene={scene} hiddenKinds={hidden} onRecenter={onRecenter} onOpen={onOpen} />;
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-paper">
      <div className="flex flex-wrap items-center gap-3 border-b border-hairline px-4 py-2">
        <button
          type="button"
          aria-label="back"
          disabled={back.length === 0}
          onClick={goBack}
          className="grid h-7 w-7 place-items-center rounded-r6 text-ink-1 hover:bg-vellum disabled:opacity-30"
        >
          <Lucide name="arrow-left" size={14} />
        </button>
        <GraphFocusPicker current={focusTitle} onPick={recenter} />
        <label className="flex items-center gap-2 font-mono text-11 text-ink-2">
          depth
          <input
            type="range"
            min={1}
            max={3}
            step={1}
            value={depth}
            aria-label="depth"
            disabled={wholeVault}
            onChange={(e) => setDepth(Number(e.target.value) as GraphDepth)}
          />
          <span className="tabular-nums text-ink-1">{depth}</span>
        </label>
        <button
          type="button"
          aria-pressed={wholeVault}
          onClick={() => setWholeVault(!wholeVault)}
          className={`rounded-pill border px-3 py-[5px] font-mono text-11 ${
            wholeVault ? 'border-neon bg-neon text-[#08130d]' : 'border-hairline text-ink-1 hover:text-ink-0'
          }`}
        >
          whole vault
        </button>
      </div>
      <div className="relative flex flex-1 overflow-hidden">
        {body}
        {!wholeVault && ego.data?.truncated && !status.isError && (
          <div
            role="status"
            className="absolute left-4 top-4 z-10 rounded-pill border border-hairline bg-paper/70 px-3 py-[6px] font-mono text-11 text-ink-1 backdrop-blur-md"
          >
            {`showing the nearest ${EGO_NODE_CAP} pages — the neighbourhood is larger`}
          </div>
        )}
        {wholeVault && vault.data && vault.data.nodes.length > 0 && (
          <div
            role="status"
            className="absolute left-4 top-4 z-10 rounded-pill border border-hairline bg-paper/70 px-3 py-[6px] font-mono text-11 text-ink-1 backdrop-blur-md"
          >
            {`whole vault · ${vault.data.nodes.length} notes · click a note to centre on it`}
          </div>
        )}
        <div aria-label="kinds" className="absolute bottom-4 left-4 z-10 flex max-w-[70%] flex-wrap gap-[6px]">
          {NOTE_KINDS.map((kind) => (
            <button
              key={kind}
              type="button"
              aria-pressed={!hidden.has(kind)}
              onClick={() => toggleKind(kind)}
              className={chip(!hidden.has(kind))}
            >
              <span className="h-[8px] w-[8px] rounded-full" style={{ background: KIND_COLORS[kind] }} />
              {KIND_LABELS[kind]}
            </button>
          ))}
          <span className="flex items-center gap-[6px] px-2 font-mono text-11 text-ink-2">
            <span className="h-[8px] w-[8px] rounded-full border" style={{ borderColor: GHOST_COLOR }} />
            not written yet
          </span>
        </div>
      </div>
    </div>
  );
}
