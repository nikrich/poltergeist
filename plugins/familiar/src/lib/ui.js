// Pure render-decision helpers for the Familiar renderer. Kept separate from
// DOM assembly (renderer.js) so the branching logic is unit-testable without
// a document.

export function toggleLoop(loop) {
  return { ...loop, status: loop.status === 'done' ? 'open' : 'done' };
}

export function statusLine(status) {
  if (status.running) return 'Running sweep…';
  const last = status.lastRuns[status.lastRuns.length - 1];
  const parts = [];
  if (last && !last.ok) parts.push(`Last run failed: ${last.error}`);
  else if (last) parts.push(`Last run ${new Date(last.finishedAt).toLocaleString()}`);
  if (status.nextRunAt) parts.push(`Next run ${new Date(status.nextRunAt).toLocaleString()}`);
  return parts.join(' · ') || 'No runs yet';
}

export function scheduleFields(cadence) {
  return { showDay: cadence !== 'daily' };
}

export function briefingSubtitle(cadence) {
  return `${cadence === 'daily' ? 'daily' : 'weekly'} briefing · your chief of staff`;
}
