import { describe, expect, it } from 'vitest';
import { planPolishApply } from '../polishApply.js';

describe('planPolishApply', () => {
  it('refuses when the doc changed since Polish started', () => {
    expect(planPolishApply({ current: 'b', startText: 'a', text: 'c' })).toBe('stale');
  });
  it('is a no-op when the composed text equals the start text', () => {
    expect(planPolishApply({ current: 'a', startText: 'a', text: 'a' })).toBe('noop');
  });
  it('applies otherwise', () => {
    expect(planPolishApply({ current: 'a', startText: 'a', text: 'c' })).toBe('apply');
  });
});
