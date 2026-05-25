import type { AgendaItem } from '../shared/api-types';

const LEAD_MINUTES = 15;

export function shouldFireNow(
  event: AgendaItem,
  now: Date,
  notified: ReadonlySet<string>,
): boolean {
  if (event.status !== 'upcoming') return false;
  if (notified.has(event.id)) return false;
  const match = event.time.match(/^(\d{2}):(\d{2})$/);
  if (!match) return false;
  const start = new Date(now);
  start.setHours(Number(match[1]), Number(match[2]), 0, 0);
  const fireAt = start.getTime() - LEAD_MINUTES * 60_000;
  // Window: [fireAt, start). If we missed fireAt by ≤15 min but the meeting
  // hasn't started yet, fire (covers an app that booted just before the
  // meeting starts).
  return now.getTime() >= fireAt && now.getTime() < start.getTime();
}
