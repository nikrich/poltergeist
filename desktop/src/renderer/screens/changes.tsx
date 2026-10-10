import { useMemo, useState } from 'react';
import { ApiError } from '../lib/api/client';
import {
  useChange,
  useChanges,
  useDismissChangesWarning,
  useRevertChange,
  useUndoRevert,
} from '../lib/api/hooks';
import { formatRelativeTime } from '../lib/format';
import { actorLabel } from '../components/HistoryDrawer';
import { LineDiffView } from '../components/LineDiffView';
import { Btn } from '../components/Btn';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';
import { TopBar } from '../components/TopBar';
import { useNoteView } from '../stores/note-view';
import { toast } from '../stores/toast';
import type { ChangeOp, ChangeSummary } from '../../shared/api-types';

export const ACTOR_FILTERS: ReadonlyArray<{ id: string | null; label: string }> = [
  { id: null, label: 'all' },
  { id: 'assistant', label: '✦ assistant' },
  { id: 'mcp', label: '⌁ mcp' },
  { id: 'plugin', label: '⧉ plugins' },
  { id: 'worker', label: '⚙ jobs' },
];

const OP_LABEL: Record<ChangeOp, string> = {
  create: 'created',
  modify: 'edited',
  delete: 'deleted',
  move: 'moved',
};

/** Local calendar day of an ISO timestamp, as YYYY-MM-DD (locale-free). */
export function dayKey(ts: string): string {
  const d = new Date(ts);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Items arrive newest first, so days come out newest first too. */
export function groupByDay(items: ChangeSummary[]): Array<[string, ChangeSummary[]]> {
  const groups = new Map<string, ChangeSummary[]>();
  for (const c of items) {
    const key = dayKey(c.ts);
    const list = groups.get(key);
    if (list) list.push(c);
    else groups.set(key, [c]);
  }
  return [...groups.entries()];
}

function ChangeRow({ change }: { change: ChangeSummary }) {
  const [showDiff, setShowDiff] = useState(false);
  const [conflict, setConflict] = useState(false);
  const detail = useChange(showDiff || conflict ? change.id : null);
  const revert = useRevertChange();
  const undo = useUndoRevert();
  const openNote = useNoteView((s) => s.open);
  const reverted = change.status === 'reverted';
  const busy = revert.isPending || undo.isPending;
  const path = change.destPath ?? change.path;

  const act = async (force: boolean) => {
    const mutation = reverted ? undo : revert;
    try {
      await mutation.mutateAsync({ id: change.id, force });
      setConflict(false);
      toast.success(reverted ? 'change re-applied' : 'change reverted — the previous version is back');
    } catch (err) {
      if (!force && err instanceof ApiError && err.status === 409) {
        setConflict(true);
        return;
      }
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`${reverted ? 'undo' : 'revert'} failed: ${message}`);
    }
  };

  const expected = detail.data ? (reverted ? detail.data.before : detail.data.after) : null;

  return (
    <li data-testid={`change-${change.id}`} className="border-b border-hairline py-2">
      <div className="flex items-center gap-3 text-12">
        <span className="flex-shrink-0 rounded-sm bg-fog px-[6px] py-[1px] font-mono text-10 text-ink-1">
          {actorLabel(change.actor)}
        </span>
        {path.endsWith('.md') ? (
          <button
            type="button"
            onClick={() => openNote(path)}
            className="min-w-0 cursor-pointer truncate border-none bg-transparent p-0 text-left text-ink-0 hover:underline"
          >
            {path}
          </button>
        ) : (
          <span className="min-w-0 truncate text-ink-0">{path}</span>
        )}
        <span className="flex-shrink-0 text-ink-2">{OP_LABEL[change.op]}</span>
        <span className="min-w-0 flex-1 truncate text-ink-2">{change.reason}</span>
        <span className="flex-shrink-0 font-mono text-10 text-ink-3">
          {formatRelativeTime(change.ts)}
        </span>
        <Btn variant="ghost" size="sm" onClick={() => setShowDiff((v) => !v)}>
          {showDiff ? 'hide diff' : 'diff'}
        </Btn>
        {change.status === 'applied' && (
          <Btn variant="secondary" size="sm" disabled={busy} onClick={() => void act(false)}>
            revert
          </Btn>
        )}
        {reverted && (
          <>
            <span className="font-mono text-10 text-ink-3">reverted</span>
            <Btn variant="ghost" size="sm" disabled={busy} onClick={() => void act(false)}>
              undo
            </Btn>
          </>
        )}
      </div>
      {showDiff && detail.data && (
        <LineDiffView
          testId={`change-diff-${change.id}`}
          className="mt-2 max-h-[320px]"
          oldText={detail.data.before ?? ''}
          newText={detail.data.after ?? ''}
          legend="- before · + after"
        />
      )}
      {conflict && (
        <div role="alert" className="mt-2 rounded-sm border border-oxblood/30 bg-oxblood/10 p-2 text-12">
          <p className="m-0 mb-2 text-ink-0">
            This note changed since. {reverted ? 'Re-apply' : 'Revert'} anyway? The current version
            stays in page history.
          </p>
          {detail.data && (
            <LineDiffView
              testId={`change-drift-${change.id}`}
              className="mb-2 max-h-[240px]"
              oldText={expected ?? ''}
              newText={detail.data.current ?? ''}
              legend="- expected · + on disk now"
            />
          )}
          <div className="flex gap-2">
            <Btn variant="danger" size="sm" disabled={busy} onClick={() => void act(true)}>
              {reverted ? 'undo anyway' : 'revert anyway'}
            </Btn>
            <Btn variant="ghost" size="sm" onClick={() => setConflict(false)}>
              cancel
            </Btn>
          </div>
        </div>
      )}
    </li>
  );
}

/** Spec B §6 (slice B2): every assistant / MCP / plugin / job change, with a
 * diff and one-click revert. B3 adds the Pending section above the history. */
export function ChangesScreen() {
  const [actor, setActor] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const changes = useChanges({ actor, q: query.trim() || null });
  const dismiss = useDismissChangesWarning();
  const groups = useMemo(
    () => groupByDay((changes.data?.items ?? []).filter((c) => c.status !== 'pending')),
    [changes.data],
  );

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <TopBar title="changes" subtitle="what assistants, plugins and jobs changed in your notes" />
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {changes.data?.degraded && (
          <div
            role="alert"
            className="mb-3 flex items-center gap-3 rounded-sm border border-oxblood/30 bg-oxblood/10 px-3 py-2 text-12 text-oxblood"
          >
            <span className="flex-1">some changes may be missing; see page history</span>
            <Btn variant="ghost" size="sm" onClick={() => dismiss.mutate()}>
              dismiss
            </Btn>
          </div>
        )}
        <div className="mb-4 flex flex-wrap items-center gap-2">
          {ACTOR_FILTERS.map((f) => (
            <button
              key={f.label}
              type="button"
              aria-pressed={actor === f.id}
              onClick={() => setActor(f.id)}
              className={`cursor-pointer rounded-r6 border px-[10px] py-[3px] text-12 ${
                actor === f.id
                  ? 'border-hairline-2 bg-vellum text-ink-0'
                  : 'border-transparent bg-transparent text-ink-2 hover:bg-vellum'
              }`}
            >
              {f.label}
            </button>
          ))}
          <input
            aria-label="filter by path"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="path contains…"
            className="ml-auto w-[220px] rounded-r6 border border-hairline bg-paper px-2 py-[3px] text-12 text-ink-0"
          />
        </div>
        {changes.isError ? (
          <PanelError
            message={`could not load changes: ${changes.error instanceof Error ? changes.error.message : 'unknown error'}`}
            onRetry={() => void changes.refetch()}
          />
        ) : changes.isLoading ? null : groups.length === 0 ? (
          <PanelEmpty icon="history" message="nothing has changed your notes yet" />
        ) : (
          groups.map(([day, items]) => (
            <section key={day} aria-label={day} className="mb-5">
              <h2 className="m-0 mb-2 font-mono text-10 uppercase tracking-eyebrow text-ink-2">
                {day}
              </h2>
              <ul className="m-0 list-none p-0">
                {items.map((c) => (
                  <ChangeRow key={c.id} change={c} />
                ))}
              </ul>
            </section>
          ))
        )}
      </div>
    </div>
  );
}
