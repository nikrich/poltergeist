import { describe, expect, it } from 'vitest';
import { settingsSchema } from '../../shared/settings-schema';

describe('settings schema — editor keys (A4)', () => {
  it('focusMode is a boolean', () => {
    expect(settingsSchema.shape.focusMode.safeParse(true).success).toBe(true);
    expect(settingsSchema.shape.focusMode.safeParse('yes').success).toBe(false);
  });

  it('readAloudVoice accepts any voice id, including empty for auto', () => {
    expect(settingsSchema.shape.readAloudVoice.safeParse('').success).toBe(true);
    expect(
      settingsSchema.shape.readAloudVoice.safeParse('com.apple.voice.compact.en-US.Samantha')
        .success,
    ).toBe(true);
    expect(settingsSchema.shape.readAloudVoice.safeParse('x'.repeat(513)).success).toBe(false);
    expect(settingsSchema.shape.readAloudVoice.safeParse(3).success).toBe(false);
  });

  it('readAloudRate is a number from 0.5 to 2', () => {
    expect(settingsSchema.shape.readAloudRate.safeParse(0.5).success).toBe(true);
    expect(settingsSchema.shape.readAloudRate.safeParse(2).success).toBe(true);
    expect(settingsSchema.shape.readAloudRate.safeParse(0.4).success).toBe(false);
    expect(settingsSchema.shape.readAloudRate.safeParse(2.1).success).toBe(false);
    expect(settingsSchema.shape.readAloudRate.safeParse('1').success).toBe(false);
  });
});
