import { describe, it, expect } from 'vitest';
import { shouldFireNow } from '../meeting-notifier';
import type { AgendaItem } from '../../shared/api-types';

function makeEvent(time: string, status: AgendaItem['status'] = 'upcoming'): AgendaItem {
  return { id: `evt-${time}`, time, duration: '30m', title: 't', with: [], status };
}

describe('shouldFireNow', () => {
  const now = new Date('2026-05-25T08:46:00+02:00');

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
