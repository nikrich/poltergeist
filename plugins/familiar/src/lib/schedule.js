const DAYS = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];

export function lastScheduledSlot(config, now) {
  const target = DAYS.indexOf(config.day);
  const d = new Date(now);
  d.setHours(config.hour, 0, 0, 0);
  d.setDate(d.getDate() - ((d.getDay() - target + 7) % 7));
  if (d > now) d.setDate(d.getDate() - 7);
  return d;
}

export function isRunDue(config, state, now = new Date()) {
  const s = state ?? {};
  if (!s.lastSuccessfulRunAt) return true;
  return new Date(s.lastSuccessfulRunAt) < lastScheduledSlot(config, now);
}

// True when the most recent attempt failed (no success recorded since it
// started) and it happened within `cooldownMs` of `now` — used to stop a
// persistently-failing sweep from retrying on every 15-min tick forever.
// Manual 'run' IPC calls bypass this predicate entirely (see main.js tick()).
export function inFailureCooldown(state, now, cooldownMs = 4 * 3600_000) {
  const s = state ?? {};
  if (!s.lastAttemptAt) return false;
  const lastAttempt = new Date(s.lastAttemptAt).getTime();
  const lastSuccess = s.lastSuccessfulRunAt ? new Date(s.lastSuccessfulRunAt).getTime() : 0;
  const attemptFailed = lastAttempt > lastSuccess;
  const withinCooldown = now.getTime() - lastAttempt < cooldownMs;
  return attemptFailed && withinCooldown;
}

export function nextRunAt(config, now = new Date()) {
  const next = new Date(lastScheduledSlot(config, now));
  next.setDate(next.getDate() + 7);
  return next;
}
