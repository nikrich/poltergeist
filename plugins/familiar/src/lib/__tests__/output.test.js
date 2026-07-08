import { describe, expect, it } from 'vitest';
import { parseSweepOutput } from '../output.js';

const GOOD = {
  briefingMarkdown: '# Briefing',
  memoryMarkdown: '# Memory',
  openLoops: [{ id: 'loop-a', text: 't', owedTo: null, sourcePath: 'a.md', firstSeen: '2026-07-01', status: 'open' }],
  decisions: [{ date: '2026-07-01', text: 'd', sourcePath: 'a.md' }],
};

describe('parseSweepOutput', () => {
  it('prefers structured output', () => {
    expect(parseSweepOutput({ text: 'garbage', structured: GOOD })).toEqual(GOOD);
  });
  it('falls back to fenced JSON in text', () => {
    const text = 'Here you go:\n```json\n' + JSON.stringify(GOOD) + '\n```\n';
    expect(parseSweepOutput({ text, structured: null })).toEqual(GOOD);
  });
  it('throws with the missing key named', () => {
    const bad = { ...GOOD };
    delete bad.openLoops;
    expect(() => parseSweepOutput({ text: '', structured: bad })).toThrow(/openLoops/);
  });
  it('throws on a loop with a bad id', () => {
    const bad = { ...GOOD, openLoops: [{ ...GOOD.openLoops[0], id: 'Bad Id!' }] };
    expect(() => parseSweepOutput({ text: '', structured: bad })).toThrow(/id/);
  });
  it('throws on invalid status', () => {
    const bad = { ...GOOD, openLoops: [{ ...GOOD.openLoops[0], status: 'wontfix' }] };
    expect(() => parseSweepOutput({ text: '', structured: bad })).toThrow(/status/);
  });
});
