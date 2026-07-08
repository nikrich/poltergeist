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
  if (!state.lastSuccessfulRunAt) return true;
  return new Date(state.lastSuccessfulRunAt) < lastScheduledSlot(config, now);
}

export function nextRunAt(config, now = new Date()) {
  const next = new Date(lastScheduledSlot(config, now));
  next.setDate(next.getDate() + 7);
  return next;
}
