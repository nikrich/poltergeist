import { describe, expect, it } from 'vitest';
import { isRunDue, lastScheduledSlot, nextRunAt } from '../schedule.js';

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
});

describe('nextRunAt', () => {
  it('is one week after the last slot', () => {
    expect(nextRunAt(CFG, WED)).toEqual(new Date(2026, 6, 13, 7, 0, 0));
  });
});
