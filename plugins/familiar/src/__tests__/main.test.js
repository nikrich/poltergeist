import { describe, expect, it } from 'vitest';
import { validateConfigPartial } from '../main.js';

describe('validateConfigPartial', () => {
  it('accepts cadence: daily', () => {
    expect(() => validateConfigPartial({ cadence: 'daily' })).not.toThrow();
  });

  it('accepts cadence: weekly', () => {
    expect(() => validateConfigPartial({ cadence: 'weekly' })).not.toThrow();
  });

  it('rejects an unknown cadence string, naming the allowed values', () => {
    expect(() => validateConfigPartial({ cadence: 'hourly' })).toThrow(
      /config\.cadence must be one of daily, weekly; got "hourly"/,
    );
  });

  it('rejects a non-string cadence', () => {
    expect(() => validateConfigPartial({ cadence: 7 })).toThrow(
      /config\.cadence must be one of daily, weekly; got 7/,
    );
  });

  it('leaves a partial without cadence unaffected', () => {
    expect(() => validateConfigPartial({ hour: 9 })).not.toThrow();
  });

  it('still rejects an invalid day (regression)', () => {
    expect(() => validateConfigPartial({ day: 'someday' })).toThrow(/config\.day must be one of/);
  });
});
