import { describe, expect, it } from 'vitest';
import { statusLine, toggleLoop } from '../ui.js';

const LOOP = { id: 'loop-a', text: 't', owedTo: null, sourcePath: 'a.md', firstSeen: '2026-07-01', status: 'open' };

describe('toggleLoop', () => {
  it('open → done and back', () => {
    expect(toggleLoop(LOOP).status).toBe('done');
    expect(toggleLoop({ ...LOOP, status: 'done' }).status).toBe('open');
  });
  it('stale toggles to done', () => {
    expect(toggleLoop({ ...LOOP, status: 'stale' }).status).toBe('done');
  });
});

describe('statusLine', () => {
  it('describes a healthy idle state', () => {
    const s = statusLine({ running: false, lastRuns: [{ ok: true, finishedAt: '2026-07-06T07:05:00Z' }], nextRunAt: '2026-07-13T07:00:00.000Z' });
    expect(s).toContain('Next run');
    expect(s).not.toContain('failed');
  });
  it('surfaces a failed last run', () => {
    const s = statusLine({ running: false, lastRuns: [{ ok: false, error: 'boom' }], nextRunAt: '2026-07-13T07:00:00.000Z' });
    expect(s).toContain('failed');
    expect(s).toContain('boom');
  });
  it('shows running state', () => {
    expect(statusLine({ running: true, lastRuns: [], nextRunAt: null })).toContain('Running');
  });
});
