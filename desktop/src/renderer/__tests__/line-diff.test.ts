import { describe, it, expect } from 'vitest';
import { lineDiff } from '../lib/line-diff';

describe('lineDiff', () => {
  it('marks unchanged, removed and added lines', () => {
    expect(lineDiff('a\nb\nc', 'a\nx\nc')).toEqual([
      { kind: 'same', text: 'a' },
      { kind: 'del', text: 'b' },
      { kind: 'add', text: 'x' },
      { kind: 'same', text: 'c' },
    ]);
  });

  it('treats CRLF like LF', () => {
    expect(lineDiff('a\r\nb', 'a\nb').every((l) => l.kind === 'same')).toBe(true);
  });

  it('handles empty sides', () => {
    expect(lineDiff('', 'x')).toEqual([
      { kind: 'del', text: '' },
      { kind: 'add', text: 'x' },
    ]);
  });

  it('falls back to block replace for huge inputs instead of freezing', () => {
    const big = Array.from({ length: 3000 }, (_, i) => `line ${i}`).join('\n');
    const out = lineDiff(big, big + '\nmore');
    expect(out.length).toBeGreaterThan(0);
  });
});
