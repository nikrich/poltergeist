import { describe, expect, it } from 'vitest';
import {
  mergeDecisions, mergeLoops, parseDecisions, parseOpenLoops,
  renderDecisions, renderOpenLoops,
} from '../trackers.js';

const LOOP = {
  id: 'loop-send-doc', text: 'Send the doc', owedTo: 'Pieter',
  sourcePath: '20-contexts/x.md', firstSeen: '2026-07-01', status: 'open',
};

describe('open loops round-trip', () => {
  it('render → parse is identity', () => {
    const loops = [
      LOOP,
      { ...LOOP, id: 'loop-b', status: 'done' },
      { ...LOOP, id: 'loop-c', status: 'stale', owedTo: null },
      { ...LOOP, id: 'loop-d', status: 'dismissed' },
    ];
    const md = renderOpenLoops(loops, []);
    expect(parseOpenLoops(md)).toEqual({ loops, unparsed: [] });
  });
  it('malformed list lines survive as unparsed', () => {
    const md = '# Open loops\n\n- hand-written todo without id\n';
    const { loops, unparsed } = parseOpenLoops(md);
    expect(loops).toEqual([]);
    expect(unparsed).toEqual(['- hand-written todo without id']);
    expect(renderOpenLoops(loops, unparsed)).toContain('## Unparsed');
  });
});

describe('mergeLoops', () => {
  it('model flips open→done', () => {
    const merged = mergeLoops([LOOP], [{ ...LOOP, status: 'done' }]);
    expect(merged[0].status).toBe('done');
  });
  it('user done/dismissed wins over model', () => {
    const current = [{ ...LOOP, status: 'dismissed' }, { ...LOOP, id: 'loop-b', status: 'done' }];
    const fromModel = [{ ...LOOP, status: 'open' }, { ...LOOP, id: 'loop-b', status: 'open' }];
    const merged = mergeLoops(current, fromModel);
    expect(merged.map((l) => l.status)).toEqual(['dismissed', 'done']);
  });
  it('model cannot dismiss', () => {
    const merged = mergeLoops([LOOP], [{ ...LOOP, status: 'dismissed' }]);
    expect(merged[0].status).toBe('open');
    const fresh = mergeLoops([], [{ ...LOOP, id: 'loop-new', status: 'dismissed' }]);
    expect(fresh[0].status).toBe('open');
  });
  it('loops omitted by the model are kept', () => {
    const merged = mergeLoops([LOOP], []);
    expect(merged).toEqual([LOOP]);
  });
  it('new model loops are appended', () => {
    const merged = mergeLoops([LOOP], [{ ...LOOP, id: 'loop-new' }]);
    expect(merged.map((l) => l.id)).toEqual(['loop-send-doc', 'loop-new']);
  });
});

describe('decisions', () => {
  const DEC = { date: '2026-07-01', text: 'Use plugin architecture', sourcePath: 'a.md' };
  it('round-trips', () => {
    expect(parseDecisions(renderDecisions([DEC]))).toEqual([DEC]);
  });
  it('merge appends new, dedups by date+text', () => {
    const merged = mergeDecisions([DEC], [DEC, { ...DEC, text: 'Another' }]);
    expect(merged.length).toBe(2);
  });
});
