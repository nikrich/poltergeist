import { describe, expect, it } from 'vitest';
import { applyHunks, diffLines, hunks, wordDiff } from '../lineDiff.js';

const A = ['INT. A - DAY', '', 'Mara wait.', '', 'MARA', 'Now?'];
const B = ['INT. A - DAY', '', 'Mara waits.', '', 'MARA', 'Now?', '', 'She sits.'];

describe('lineDiff', () => {
  it('diffs lines with LCS', () => {
    expect(diffLines(['a', 'b', 'c'], ['a', 'x', 'c'])).toEqual([
      { type: 'equal', text: 'a' }, { type: 'del', text: 'b' }, { type: 'add', text: 'x' }, { type: 'equal', text: 'c' },
    ]);
  });
  it('groups into hunks and re-applies all/none/partial exactly', () => {
    const hs = hunks(A, B);
    expect(hs.filter((h) => h.type === 'change')).toEqual([
      { type: 'change', del: ['Mara wait.'], add: ['Mara waits.'] },
      { type: 'change', del: [], add: ['', 'She sits.'] },
    ]);
    expect(applyHunks(hs, () => true)).toEqual(B);
    expect(applyHunks(hs, () => false)).toEqual(A);
    expect(applyHunks(hs, (i) => i === 0)).toEqual(['INT. A - DAY', '', 'Mara waits.', '', 'MARA', 'Now?']);
  });
  it('handles empty sides', () => {
    expect(hunks([], ['x'])).toEqual([{ type: 'change', del: [], add: ['x'] }]);
    expect(hunks(['x'], [])).toEqual([{ type: 'change', del: ['x'], add: [] }]);
    expect(hunks([], [])).toEqual([]);
  });
  it('word-diffs a single edited line, merging runs', () => {
    expect(wordDiff('Mara wait here.', 'Mara waits here.')).toEqual([
      { type: 'equal', text: 'Mara ' }, { type: 'del', text: 'wait' }, { type: 'add', text: 'waits' }, { type: 'equal', text: ' here.' },
    ]);
  });
  it('falls back to a full replace for huge inputs', () => {
    const big = Array.from({ length: 2100 }, (_, k) => `l${k}`);
    const ops = diffLines(big, [...big].reverse());
    expect(ops.filter((o) => o.type === 'equal')).toHaveLength(0);
  });
});
