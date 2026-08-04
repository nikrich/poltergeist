export function mmss(seconds: number): string {
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

/**
 * Renders an ISO timestamp in a compact relative form for UI density.
 *
 * < 1 min  → "just now"
 * < 1 hr   → "5m ago"
 * < 1 day  → "3h ago"
 * < 7 days → "3d ago"
 * else     → "may 8" (short month + day; year only when not current)
 *
 * Returns "never" for null/empty/unparseable input.
 */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return 'never';
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return 'never';
  const diffMs = Date.now() - when.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  const month = MONTHS[when.getMonth()];
  const day = when.getDate();
  const sameYear = when.getFullYear() === new Date().getFullYear();
  return sameYear ? `${month} ${day}` : `${month} ${day}, ${when.getFullYear()}`;
}
