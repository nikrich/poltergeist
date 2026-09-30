import { describe, expect, it } from 'vitest';
import { composePolished, polishDocument, polishUnits } from '../polish.js';

const DOC = 'FADE IN:\n\nINT. A - DAY\n\nmara wait.\n\nMARA\nNow?\n\nINT. B - DAY\n\nJoe run.\n\nJOE\nGo!\n\nINT. C - DAY\n\nOne.\nTwo.\nThree.\nFour.\nFive.\nSix.\n';

function fakePlugin(handler) {
  let inFlight = 0;
  const stats = { max: 0, calls: 0 };
  return {
    stats,
    sidecar: {
      request: async (method, path, body) => {
        stats.calls++;
        inFlight++;
        stats.max = Math.max(stats.max, inFlight);
        await new Promise((r) => setTimeout(r, 5));
        inFlight--;
        const section = body.prompt.split('## Section\n')[1];
        return handler(section, body);
      },
    },
  };
}

describe('polishUnits', () => {
  it('makes one unit for the preamble and one per scene', () => {
    const { units } = polishUnits(DOC);
    expect(units.map((u) => [u.kind, u.heading])).toEqual([['pre', 'Opening'], ['scene', 'INT. A - DAY'], ['scene', 'INT. B - DAY'], ['scene', 'INT. C - DAY']]);
  });
});

describe('polishDocument', () => {
  it('polishes every section with at most 3 in flight, keeping order and flagging failures', async () => {
    const plugin = fakePlugin((section, body) => {
      expect(body.budgetUsd).toBe(0.5);
      if (section.startsWith('INT. A')) return { ok: true, data: { text: '', structured: { fountain: 'INT. A - DAY\n\nMara waits.\n\nMARA\nNow?', changes: 'grammar' }, error: null } };
      if (section.startsWith('INT. B')) return { ok: true, data: { text: '', structured: null, error: 'Budget exceeded' } };
      if (section.startsWith('INT. C')) return { ok: true, data: { text: '', structured: { fountain: 'INT. C - DAY\n\nOne.' }, error: null } };
      return { ok: true, data: { text: '', structured: { fountain: section.trim() }, error: null } };
    });
    const progress = [];
    const out = await polishDocument(plugin, { text: DOC, passes: ['formatting', 'language'], onProgress: (p) => progress.push(p) });
    expect(plugin.stats.max).toBeLessThanOrEqual(3);
    expect(out.results.map((r) => r.status)).toEqual(['unchanged', 'changed', 'error', 'rejected']);
    expect(out.results[2].reason).toBe('Budget exceeded');
    expect(out.results[3].reason).toMatch(/lost/);
    expect(out.results[1].summary).toBe('grammar');
    expect(progress.at(-1)).toEqual({ done: 4, total: 4 });
  });
  it('rejects a scene polished into prose with no cue or heading', async () => {
    const plugin = fakePlugin((section) => {
      if (section.startsWith('INT. A')) return { ok: true, data: { text: '', structured: { fountain: 'Mara waits and asks now.\nShe sits.\nShe stands.\nShe waits.' }, error: null } };
      return { ok: true, data: { text: '', structured: { fountain: section.trim() }, error: null } };
    });
    const out = await polishDocument(plugin, { text: DOC, passes: ['language'] });
    expect(out.results[1].status).toBe('rejected');
    expect(out.results[1].reason).toMatch(/structure/);
  });
  it('requires at least one pass and honours cancellation', async () => {
    await expect(polishDocument(fakePlugin(() => ({})), { text: DOC, passes: [] })).rejects.toThrow(/at least one/);
    const ctrl = new AbortController();
    ctrl.abort();
    await expect(polishDocument(fakePlugin(() => ({})), { text: DOC, passes: ['language'], signal: ctrl.signal })).rejects.toThrow(/cancelled/);
  });
});

describe('composePolished', () => {
  const result = {
    sb: polishUnits(DOC).sb,
    results: polishUnits(DOC).units.map((u) => ({ ...u, polished: u.text, status: 'unchanged' })),
  };
  result.results[1] = { ...result.results[1], polished: 'INT. A - DAY\n\nMara waits.\n\nMARA\nNow?\n\nShe sits.', status: 'changed' };
  it('all on = polished, all off = original, partial = exact mix', () => {
    const all = composePolished(result, () => true);
    expect(all).toContain('Mara waits.\n\nMARA\nNow?\n\nShe sits.');
    expect(composePolished(result, () => false)).toBe(DOC);
    const first = composePolished(result, (u, c) => u === 1 && c === 0);
    expect(first).toContain('Mara waits.\n\nMARA\nNow?\n\nINT. B');
    expect(first).not.toContain('She sits.');
  });
});
