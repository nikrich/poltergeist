import { describe, expect, it } from 'vitest';
import { scheduleFields, briefingSubtitle } from '../ui.js';

describe('scheduleFields', () => {
  it('hides Day for daily cadence', () => {
    expect(scheduleFields('daily').showDay).toBe(false);
  });
  it('shows Day for weekly cadence', () => {
    expect(scheduleFields('weekly').showDay).toBe(true);
  });
  it('shows Day when cadence is undefined', () => {
    expect(scheduleFields(undefined).showDay).toBe(true);
  });
});

describe('briefingSubtitle', () => {
  it('says daily for daily cadence', () => {
    expect(briefingSubtitle('daily')).toBe('daily briefing · your chief of staff');
  });
  it('says weekly for weekly cadence', () => {
    expect(briefingSubtitle('weekly')).toBe('weekly briefing · your chief of staff');
  });
  it('defaults to weekly wording when cadence is absent', () => {
    expect(briefingSubtitle(undefined)).toBe('weekly briefing · your chief of staff');
  });
});
