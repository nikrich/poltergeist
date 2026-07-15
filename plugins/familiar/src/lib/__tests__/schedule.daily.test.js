import { describe, expect, it } from 'vitest';
import { isRunDue, lastScheduledSlot, nextRunAt } from '../schedule.js';

const CFG = { cadence: 'daily', hour: 7 };
// 2026-07-08 is a Wednesday.
const WED_MORNING = new Date(2026, 6, 8, 8, 0, 0);

describe('lastScheduledSlot (daily)', () => {
  it('at 08:00 local returns today 07:00', () => {
    expect(lastScheduledSlot(CFG, WED_MORNING)).toEqual(new Date(2026, 6, 8, 7, 0, 0));
  });
  it('before the hour rolls back to yesterday 07:00', () => {
    const early = new Date(2026, 6, 8, 6, 0, 0);
    expect(lastScheduledSlot(CFG, early)).toEqual(new Date(2026, 6, 7, 7, 0, 0));
  });
  it('exactly at the hour counts as today 07:00', () => {
    const atHour = new Date(2026, 6, 8, 7, 0, 0);
    expect(lastScheduledSlot(CFG, atHour)).toEqual(new Date(2026, 6, 8, 7, 0, 0));
  });
  it('ignores config.day', () => {
    const withDay = { ...CFG, day: 'monday' };
    expect(lastScheduledSlot(withDay, WED_MORNING)).toEqual(new Date(2026, 6, 8, 7, 0, 0));
  });
});

describe('nextRunAt (daily)', () => {
  it('is the slot plus one day', () => {
    expect(nextRunAt(CFG, WED_MORNING)).toEqual(new Date(2026, 6, 9, 7, 0, 0));
  });
});

describe('isRunDue (daily)', () => {
  it('not due before today 07:00', () => {
    const yesterday8am = new Date(2026, 6, 7, 8, 0, 0).toISOString();
    const beforeSlot = new Date(2026, 6, 8, 6, 0, 0);
    expect(isRunDue(CFG, { lastSuccessfulRunAt: yesterday8am }, beforeSlot)).toBe(false);
  });
  it('due at/after today 07:00', () => {
    const yesterday8am = new Date(2026, 6, 7, 8, 0, 0).toISOString();
    expect(isRunDue(CFG, { lastSuccessfulRunAt: yesterday8am }, new Date(2026, 6, 8, 7, 0, 0))).toBe(true);
    expect(isRunDue(CFG, { lastSuccessfulRunAt: yesterday8am }, WED_MORNING)).toBe(true);
  });
  it('first run (empty state) is due immediately', () => {
    expect(isRunDue(CFG, {}, WED_MORNING)).toBe(true);
  });
  it('a missed day is caught up on a later tick', () => {
    const twoDaysAgo8am = new Date(2026, 6, 6, 8, 0, 0).toISOString();
    expect(isRunDue(CFG, { lastSuccessfulRunAt: twoDaysAgo8am }, WED_MORNING)).toBe(true);
  });
});

describe('backward compatibility', () => {
  it('a config with no cadence key still behaves weekly', () => {
    const legacy = { day: 'monday', hour: 7 };
    // 2026-07-08 is a Wednesday; 2026-07-06 the preceding Monday.
    expect(lastScheduledSlot(legacy, WED_MORNING)).toEqual(new Date(2026, 6, 6, 7, 0, 0));
    expect(nextRunAt(legacy, WED_MORNING)).toEqual(new Date(2026, 6, 13, 7, 0, 0));
  });
});
