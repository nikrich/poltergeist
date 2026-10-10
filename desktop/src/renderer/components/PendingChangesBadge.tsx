import { usePendingChanges } from '../lib/api/hooks';

/** Sidebar badge (spec B §6): how many changes wait for your approval.
 * Polled every 30 s through the query the Pending section uses. */
export function PendingChangesBadge() {
  const pending = usePendingChanges();
  const count = pending.data?.pendingCount ?? 0;
  if (count === 0) return null;
  const label =
    count === 1 ? '1 change waiting for approval' : `${count} changes waiting for approval`;
  return (
    <span
      data-testid="pending-changes-badge"
      aria-label={label}
      title={label}
      className="rounded-full bg-neon/20 px-[6px] font-mono text-10 font-medium text-ink-0"
    >
      {count > 99 ? '99+' : String(count)}
    </span>
  );
}
