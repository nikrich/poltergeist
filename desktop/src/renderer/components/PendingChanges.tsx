import { useState } from 'react';
import { ApiError } from '../lib/api/client';
import { useApproveChange, useChange, usePendingChanges, useRejectChange } from '../lib/api/hooks';
import { formatRelativeTime } from '../lib/format';
import { actorLabel } from './HistoryDrawer';
import { LineDiffView } from './LineDiffView';
import { Btn } from './Btn';
import { useNoteView } from '../stores/note-view';
import { toast } from '../stores/toast';
import type { ChangeOp, ChangeSummary } from '../../shared/api-types';

const PROPOSED_OP: Record<ChangeOp, string> = {
  create: 'would create',
  modify: 'would edit',
  delete: 'would delete',
  move: 'would move',
};

const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

/** The stale-approval prompt. The drift is re-read after the 409, so forcing is
 * only offered over what is on disk now, never over the detail cached at mount. */
type Drift = { state: 'loading' } | { state: 'ready' } | { state: 'error'; message: string };

function PendingCard({ change }: { change: ChangeSummary }) {
  const detail = useChange(change.id);
  const approve = useApproveChange();
  const reject = useRejectChange();
  const openNote = useNoteView((s) => s.open);
  const [drift, setDrift] = useState<Drift | null>(null);
  const busy = approve.isPending || reject.isPending;
  const canOpen = change.op !== 'create' && change.path.endsWith('.md');
  const d = detail.data;

  const onApprove = async (force: boolean) => {
    try {
      await approve.mutateAsync({ id: change.id, force });
      toast.success('approved — the change is in your notes now');
    } catch (err) {
      if (!force && err instanceof ApiError && err.status === 409) {
        setDrift({ state: 'loading' });
        const fresh = await detail.refetch();
        const next: Drift = fresh.isError
          ? { state: 'error', message: message(fresh.error) }
          : { state: 'ready' };
        // A cancel while the drift was being re-read keeps the prompt closed.
        setDrift((cur) => (cur ? next : null));
        return;
      }
      toast.error(`approve failed: ${message(err)}`);
    }
  };

  const onReject = async () => {
    try {
      await reject.mutateAsync({ id: change.id });
      toast.success('rejected — nothing was written');
    } catch (err) {
      toast.error(`reject failed: ${message(err)}`);
    }
  };

  return (
    <li
      data-testid={`pending-${change.id}`}
      className="rounded-sm border border-hairline bg-paper p-3"
    >
      <div className="flex items-center gap-3 text-12">
        <span className="flex-shrink-0 rounded-sm bg-fog px-[6px] py-[1px] font-mono text-10 text-ink-1">
          {actorLabel(change.actor)}
        </span>
        {canOpen ? (
          <button
            type="button"
            onClick={() => openNote(change.path)}
            className="min-w-0 cursor-pointer truncate border-none bg-transparent p-0 text-left text-ink-0 hover:underline"
          >
            {change.path}
          </button>
        ) : (
          <span className="min-w-0 truncate text-ink-0">{change.path}</span>
        )}
        <span className="flex-shrink-0 text-ink-2">
          {PROPOSED_OP[change.op]}
          {change.destPath ? ` → ${change.destPath}` : ''}
        </span>
        <span className="min-w-0 flex-1 truncate text-ink-2">{change.reason}</span>
        <span className="flex-shrink-0 font-mono text-10 text-ink-3">
          {formatRelativeTime(change.ts)}
        </span>
      </div>
      <ul aria-label="why it waits" className="m-0 mt-2 flex list-none flex-wrap gap-2 p-0">
        {change.riskReasons.map((r) => (
          <li key={r} className="rounded-sm bg-oxblood/10 px-[6px] py-[1px] text-11 text-oxblood">
            {r}
          </li>
        ))}
      </ul>
      {d ? (
        <LineDiffView
          testId={`pending-diff-${change.id}`}
          className="mt-2 max-h-[320px]"
          oldText={d.before ?? ''}
          newText={d.after ?? ''}
          legend="- when proposed · + proposed"
        />
      ) : detail.isError ? (
        <p className="m-0 mt-2 text-11 text-ink-2">
          couldn&apos;t load the proposed change: {detail.error.message}
        </p>
      ) : (
        <p className="m-0 mt-2 text-11 text-ink-2">loading…</p>
      )}
      {d?.changedSince && !drift && (
        <p className="m-0 mt-2 text-11 text-ink-2">
          this note changed since the change was proposed
        </p>
      )}
      {drift ? (
        <div
          role="alert"
          className="mt-2 rounded-sm border border-oxblood/30 bg-oxblood/10 p-2 text-12"
        >
          <p className="m-0 mb-2 text-ink-0">
            This note changed since the change was proposed. Approve anyway? The current version
            stays in page history.
          </p>
          {drift.state === 'ready' && d ? (
            <LineDiffView
              testId={`pending-drift-${change.id}`}
              className="mb-2 max-h-[240px]"
              oldText={d.before ?? ''}
              newText={d.current ?? ''}
              legend="- when proposed · + on disk now"
            />
          ) : drift.state === 'error' ? (
            <p className="m-0 mb-2 text-ink-2">couldn&apos;t load what changed: {drift.message}</p>
          ) : (
            <p className="m-0 mb-2 text-ink-2">loading…</p>
          )}
          <div className="flex gap-2">
            {/* Forcing is only offered once the user can see what it replaces. */}
            <Btn
              variant="danger"
              size="sm"
              disabled={busy || drift.state !== 'ready' || !d}
              onClick={() => void onApprove(true)}
            >
              approve anyway
            </Btn>
            <Btn variant="ghost" size="sm" disabled={busy} onClick={() => void onReject()}>
              reject
            </Btn>
            <Btn variant="ghost" size="sm" onClick={() => setDrift(null)}>
              cancel
            </Btn>
          </div>
        </div>
      ) : (
        <div className="mt-2 flex gap-2">
          {/* Approval is only offered once the user can see what it writes. */}
          <Btn
            variant="primary"
            size="sm"
            disabled={busy || !d}
            onClick={() => void onApprove(false)}
          >
            approve
          </Btn>
          <Btn variant="ghost" size="sm" disabled={busy} onClick={() => void onReject()}>
            reject
          </Btn>
        </div>
      )}
    </li>
  );
}

/** Spec B §6 (slice B3): risky changes held for your approval. */
export function PendingChanges() {
  const pending = usePendingChanges();
  const items = (pending.data?.items ?? []).filter((c) => c.status === 'pending');
  if (items.length === 0) return null;
  return (
    <section aria-label="waiting for your approval" className="mb-6">
      <h2 className="m-0 mb-2 font-mono text-10 uppercase tracking-eyebrow text-oxblood">
        waiting for your approval · {items.length}
      </h2>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {items.map((c) => (
          <PendingCard key={c.id} change={c} />
        ))}
      </ul>
    </section>
  );
}
