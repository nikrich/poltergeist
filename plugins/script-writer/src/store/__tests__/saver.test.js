import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createSaver, shouldOfferDraft } from '../saver.js';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function harness(saveImpl) {
  const saved = [];
  const mirrored = [];
  const statuses = [];
  const saver = createSaver({
    save: vi.fn(async (c) => { await saveImpl(c); saved.push(c); }),
    mirror: vi.fn(async (c) => { mirrored.push(c); }),
    onStatus: (s, info) => statuses.push(info ? [s, info.retryInMs] : s),
  });
  return { saver, saved, mirrored, statuses };
}

describe('saver', () => {
  it('debounces to one save of the latest content', async () => {
    const h = harness(async () => {});
    h.saver.change('a');
    await vi.advanceTimersByTimeAsync(1000);
    h.saver.change('ab');
    await vi.advanceTimersByTimeAsync(1499);
    expect(h.saved).toEqual([]);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.saved).toEqual(['ab']);
    expect(h.statuses).toEqual(['dirty', 'dirty', 'saving', 'saved']);
  });

  it('on failure mirrors, backs off 2s then 4s, and saves the newest text', async () => {
    let fails = 2;
    const h = harness(async () => { if (fails-- > 0) throw new Error('sidecar down'); });
    h.saver.change('v1');
    await vi.advanceTimersByTimeAsync(1500);
    expect(h.statuses.at(-1)).toEqual(['error', 2000]);
    expect(h.mirrored).toEqual(['v1']);
    h.saver.change('v2'); // typing during an outage keeps the backoff schedule
    await vi.advanceTimersByTimeAsync(2000);
    expect(h.statuses.at(-1)).toEqual(['error', 4000]);
    expect(h.mirrored.at(-1)).toBe('v2');
    await vi.advanceTimersByTimeAsync(4000);
    expect(h.saved).toEqual(['v2']);
    expect(h.statuses.at(-1)).toBe('saved');
  });

  it('flush saves immediately and dispose stops retries', async () => {
    const h = harness(async () => {});
    h.saver.change('x');
    await h.saver.flush();
    expect(h.saved).toEqual(['x']);
    const bad = harness(async () => { throw new Error('no'); });
    bad.saver.change('y');
    await bad.saver.flush();
    bad.saver.dispose();
    await vi.advanceTimersByTimeAsync(60000);
    expect(bad.saver.status).toBe('error');
    expect(bad.mirrored).toEqual(['y']);
  });

  it('mirrors latest pending during outage on change', async () => {
    let fails = 2;
    const h = harness(async () => { if (fails-- > 0) throw new Error('outage'); });
    h.saver.change('v1');
    await vi.advanceTimersByTimeAsync(1500);
    expect(h.mirrored).toEqual(['v1']);
    h.saver.change('v2'); // during error status
    await vi.advanceTimersByTimeAsync(0); // flush microtasks
    expect(h.mirrored.at(-1)).toBe('v2');
  });

  it('dispose mirrors pending text and stops scheduling', async () => {
    const h = harness(async () => { throw new Error('fail'); });
    h.saver.change('x');
    h.saver.dispose();
    await vi.advanceTimersByTimeAsync(0); // flush microtasks for mirror
    expect(h.mirrored).toEqual(['x']);
    await vi.advanceTimersByTimeAsync(10000);
    expect(h.saved).toEqual([]); // no save attempt after dispose
  });

  it('change during in-flight save keeps status dirty and saves newer text', async () => {
    let saveResolve;
    let callCount = 0;
    const h = harness(async () => {
      callCount++;
      return new Promise((r) => { if (callCount === 1) saveResolve = r; else r(); });
    });
    h.saver.change('v1');
    await vi.advanceTimersByTimeAsync(1500); // triggers save
    expect(h.saver.status).toBe('saving');
    h.saver.change('v2'); // during in-flight save
    saveResolve(); // resolve the first save
    await vi.advanceTimersByTimeAsync(0); // flush microtasks
    expect(h.saver.status).toBe('dirty'); // stays dirty, not saved
    expect(h.saved).toEqual(['v1']); // first save completes
    await vi.advanceTimersByTimeAsync(1500); // second debounce
    expect(h.saved).toEqual(['v1', 'v2']);
    expect(h.saver.status).toBe('saved');
  });

  it('flush during backoff retries immediately with latest text', async () => {
    let fails = 1;
    const h = harness(async () => { if (fails-- > 0) throw new Error('fail'); });
    h.saver.change('v1');
    await vi.advanceTimersByTimeAsync(1500); // first save fails
    expect(h.mirrored).toEqual(['v1']);
    h.saver.change('v2'); // update during backoff
    await h.saver.flush(); // flush immediately
    expect(h.saved).toEqual(['v2']);
    expect(h.saver.status).toBe('saved');
  });

  it('successful save with pending never leaves status saved until newer text saves', async () => {
    let saveResolve;
    let callCount = 0;
    const h = harness(async () => {
      callCount++;
      return new Promise((r) => { if (callCount === 1) saveResolve = r; else r(); });
    });
    h.saver.change('v1');
    await vi.advanceTimersByTimeAsync(1500);
    expect(h.saver.status).toBe('saving');
    h.saver.change('v2');
    saveResolve();
    await vi.advanceTimersByTimeAsync(0); // microtasks
    expect(h.saver.status).toBe('dirty'); // not saved yet
    await vi.advanceTimersByTimeAsync(1500); // second save
    expect(h.saver.status).toBe('saved');
    expect(h.saved).toEqual(['v1', 'v2']);
  });
});

describe('shouldOfferDraft', () => {
  it('offers only a newer, different draft', () => {
    const meta = { updated: '2026-09-30T10:00:00.000Z' };
    expect(shouldOfferDraft(null, meta, 'a')).toBe(false);
    expect(shouldOfferDraft({ content: 'a', savedAt: '2026-09-30T11:00:00.000Z' }, meta, 'a')).toBe(false);
    expect(shouldOfferDraft({ content: 'b', savedAt: '2026-09-30T09:00:00.000Z' }, meta, 'a')).toBe(false);
    expect(shouldOfferDraft({ content: 'b', savedAt: '2026-09-30T11:00:00.000Z' }, meta, 'a')).toBe(true);
    expect(shouldOfferDraft({ content: 'b', savedAt: '2026-09-30T11:00:00.000Z' }, { updated: '' }, 'a')).toBe(true);
  });
});
