import { describe, it, expect } from 'vitest';
import { shouldFireNow } from '../meeting-notifier';
import type { AgendaItem } from '../../shared/api-types';

function makeEvent(time: string, status: AgendaItem['status'] = 'upcoming'): AgendaItem {
  return { id: `evt-${time}`, time, duration: '30m', title: 't', with: [], status };
}

describe('shouldFireNow', () => {
  // Build `now` from local components so the test is timezone-independent.
  // `shouldFireNow` uses Date#setHours (local time) to match how the sidecar
  // emits agenda HH:MM (also local — see ghostbrain/api/repo/agenda.py).
  // An ISO string with a fixed offset only "looks right" in that same tz.
  const now = new Date(2026, 4, 25, 8, 46, 0);  // May = month index 4

  it('fires when start is exactly 15 minutes away', () => {
    const event = makeEvent('09:01');  // 15 min from now
    expect(shouldFireNow(event, now, new Set())).toBe(true);
  });

  it('does not fire when start is more than 15 minutes away', () => {
    const event = makeEvent('09:30');
    expect(shouldFireNow(event, now, new Set())).toBe(false);
  });

  it('does not fire for events whose start has already passed', () => {
    const event = makeEvent('08:00');
    expect(shouldFireNow(event, now, new Set())).toBe(false);
  });

  it('does not fire when the event id was already notified', () => {
    const event = makeEvent('09:00');
    expect(shouldFireNow(event, now, new Set(['evt-09:00']))).toBe(false);
  });

  it('does not fire for recorded events', () => {
    const event = makeEvent('09:00', 'recorded');
    expect(shouldFireNow(event, now, new Set())).toBe(false);
  });

  it('returns false for events with malformed time', () => {
    const event = { ...makeEvent('09:00'), time: 'garbage' };
    expect(shouldFireNow(event, now, new Set())).toBe(false);
  });
});
