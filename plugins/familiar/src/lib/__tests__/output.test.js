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

  // Fix #1: Guard array types first
  it('throws when openLoops is not an array', () => {
    const bad = { ...GOOD, openLoops: null };
    expect(() => parseSweepOutput({ text: '', structured: bad })).toThrow(/openLoops must be an array/);
  });
  it('throws when decisions is not an array', () => {
    const bad = { ...GOOD, decisions: null };
    expect(() => parseSweepOutput({ text: '', structured: bad })).toThrow(/decisions must be an array/);
  });

  // Fix #2: Validate firstSeen format
  it('throws when loop firstSeen does not match YYYY-MM-DD format', () => {
    const bad = { ...GOOD, openLoops: [{ ...GOOD.openLoops[0], firstSeen: '2026/07/01' }] };
    expect(() => parseSweepOutput({ text: '', structured: bad })).toThrow(/loop-a.*firstSeen/);
  });

  // Fix #3: Validate decision text and sourcePath are strings
  it('throws when decision text is not a string', () => {
    const bad = { ...GOOD, decisions: [{ ...GOOD.decisions[0], text: 123 }] };
    expect(() => parseSweepOutput({ text: '', structured: bad })).toThrow(/decision text must be a string/);
  });
  it('throws when decision sourcePath is not a string', () => {
    const bad = { ...GOOD, decisions: [{ ...GOOD.decisions[0], sourcePath: 123 }] };
    expect(() => parseSweepOutput({ text: '', structured: bad })).toThrow(/decision sourcePath must be a string/);
  });

  // Fix #4: Validate owedTo is string or null
  it('throws when loop owedTo is not a string or null', () => {
    const bad = { ...GOOD, openLoops: [{ ...GOOD.openLoops[0], owedTo: 123 }] };
    expect(() => parseSweepOutput({ text: '', structured: bad })).toThrow(/loop-a.*owedTo must be a string or null/);
  });

  // Fix #5: Loosen fence regex to allow missing trailing newline
  it('parses fenced JSON without trailing newline before closing fence', () => {
    const text = 'Here you go:\n```json\n' + JSON.stringify(GOOD) + '\n```';
    expect(parseSweepOutput({ text, structured: null })).toEqual(GOOD);
  });
});
