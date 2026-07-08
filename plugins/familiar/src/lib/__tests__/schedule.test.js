import { describe, expect, it } from 'vitest';
import { inFailureCooldown, isRunDue, lastScheduledSlot, nextRunAt } from '../schedule.js';

const CFG = { cadence: 'weekly', day: 'monday', hour: 7 };
// 2026-07-08 is a Wednesday; 2026-07-06 the preceding Monday.
const WED = new Date(2026, 6, 8, 12, 0, 0);

describe('lastScheduledSlot', () => {
  it('finds the preceding Monday 07:00', () => {
    expect(lastScheduledSlot(CFG, WED)).toEqual(new Date(2026, 6, 6, 7, 0, 0));
  });
  it('same-day before the hour rolls back a week', () => {
    const monEarly = new Date(2026, 6, 6, 6, 0, 0);
    expect(lastScheduledSlot(CFG, monEarly)).toEqual(new Date(2026, 5, 29, 7, 0, 0));
  });
  it('same-day at the hour counts', () => {
    const monSeven = new Date(2026, 6, 6, 7, 0, 0);
    expect(lastScheduledSlot(CFG, monSeven)).toEqual(new Date(2026, 6, 6, 7, 0, 0));
  });
});

describe('isRunDue', () => {
  it('first run: due immediately', () => {
    expect(isRunDue(CFG, {}, WED)).toBe(true);
  });
  it('ran after the slot: not due', () => {
    expect(isRunDue(CFG, { lastSuccessfulRunAt: new Date(2026, 6, 6, 8, 0).toISOString() }, WED)).toBe(false);
  });
  it('missed slot (app closed Monday): due on Wednesday', () => {
    expect(isRunDue(CFG, { lastSuccessfulRunAt: new Date(2026, 6, 3, 9, 0).toISOString() }, WED)).toBe(true);
  });
  it('treats a missing/null/undefined state as {} rather than throwing', () => {
    expect(isRunDue(CFG, null, WED)).toBe(true);
    expect(isRunDue(CFG, undefined, WED)).toBe(true);
  });
});

describe('nextRunAt', () => {
  it('is one week after the last slot', () => {
    expect(nextRunAt(CFG, WED)).toEqual(new Date(2026, 6, 13, 7, 0, 0));
  });
});

describe('inFailureCooldown', () => {
  it('fresh state (no lastAttemptAt): false', () => {
    expect(inFailureCooldown({}, WED)).toBe(false);
  });
  it('recent failed attempt (no success since): true', () => {
    const state = { lastAttemptAt: new Date(WED.getTime() - 60_000).toISOString() };
    expect(inFailureCooldown(state, WED)).toBe(true);
  });
  it('old failed attempt (outside the cooldown window): false', () => {
    const state = { lastAttemptAt: new Date(WED.getTime() - 5 * 3600_000).toISOString() };
    expect(inFailureCooldown(state, WED)).toBe(false);
  });
  it('recent attempt that succeeded (lastSuccessfulRunAt >= lastAttemptAt): false', () => {
    const attemptAt = new Date(WED.getTime() - 60_000);
    const state = {
      lastAttemptAt: attemptAt.toISOString(),
      lastSuccessfulRunAt: attemptAt.toISOString(),
    };
    expect(inFailureCooldown(state, WED)).toBe(false);
  });
  it('handles a missing/null state', () => {
    expect(inFailureCooldown(null, WED)).toBe(false);
    expect(inFailureCooldown(undefined, WED)).toBe(false);
  });
});
