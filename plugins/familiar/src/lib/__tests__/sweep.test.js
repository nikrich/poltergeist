import { beforeEach, describe, expect, it } from 'vitest';
import { runSweep, MEMORY_PATH, LOOPS_PATH, DECISIONS_PATH } from '../sweep.js';
import { parseOpenLoops, renderOpenLoops } from '../trackers.js';

const GOOD_OUTPUT = {
  briefingMarkdown: '# Briefing\nAll clear.',
  memoryMarkdown: '# Memory\nTheme: plugins.',
  openLoops: [{ id: 'loop-ship-familiar', text: 'Ship Familiar', owedTo: null, sourcePath: '10-daily/2026-07-07.md', firstSeen: '2026-07-07', status: 'open' }],
  decisions: [{ date: '2026-07-07', text: 'Familiar is a plugin', sourcePath: '10-daily/2026-07-07.md' }],
};

// Deterministic 16-hex etag of a body, like the sidecar's (content-derived).
function etagOf(body) {
  let h = 0n;
  for (const ch of body) h = (h * 131n + BigInt(ch.codePointAt(0))) % (2n ** 64n);
  return h.toString(16).padStart(16, '0');
}

function makeFakeApi({ llmResponses, putFailure = null }) {
  const notes = new Map();       // path -> body
  const puts = [];               // recorded PUT payloads
  const putOpts = [];            // recorded PUT 4th arg, aligned with puts
  const llmCalls = [];
  const api = {
    fetch: async (method, path, body, opts) => {
      if (method === 'GET' && path.startsWith('/v1/activity')) {
        return { ok: true, data: [{ path: '10-daily/2026-07-07.md' }, { path: 'Familiar/memory.md' }] };
      }
      if (method === 'GET' && path.startsWith('/v1/notes?path=')) {
        const p = decodeURIComponent(path.slice('/v1/notes?path='.length));
        if (!notes.has(p)) return { ok: false, error: 'Note not found', status: 404 };
        return { ok: true, data: { path: p, title: p, body: notes.get(p), frontmatter: {}, etag: etagOf(notes.get(p)) } };
      }
      if (method === 'PUT' && path === '/v1/notes') {
        puts.push(body);
        putOpts.push(opts);
        if (putFailure && notes.has(body.path)) return putFailure;
        const created = !notes.has(body.path);
        notes.set(body.path, body.content);
        return { ok: true, data: { path: body.path, created, etag: etagOf(body.content) } };
      }
      if (method === 'POST' && path === '/v1/llm/run') {
        llmCalls.push(body);
        return { ok: true, data: llmResponses[Math.min(llmCalls.length - 1, llmResponses.length - 1)] };
      }
      throw new Error(`unexpected call: ${method} ${path}`);
    },
  };
  return { api, notes, puts, putOpts, llmCalls };
}

const DEPS = (api) => ({
  api,
  settings: { model: 'sonnet', budgetChars: 150000 },
  state: { lastSuccessfulRunAt: new Date(2026, 6, 6, 7, 0).toISOString() },
  now: new Date(2026, 6, 8, 7, 0),
  log: () => {},
});

describe('runSweep', () => {
  let fake;
  beforeEach(() => {
    fake = makeFakeApi({ llmResponses: [{ text: '', structured: GOOD_OUTPUT, error: null, costUsd: 0.4, durationMs: 5 }] });
    fake.notes.set('10-daily/2026-07-07.md', 'daily note body');
  });

  it('happy path writes briefing, memory, and both trackers', async () => {
    const report = await runSweep(DEPS(fake.api));
    expect(report.ok).toBe(true);
    expect(report.briefingPath).toBe('Familiar/briefings/2026-07-08.md');
    const paths = fake.puts.map((p) => p.path);
    expect(paths).toEqual(expect.arrayContaining([
      'Familiar/briefings/2026-07-08.md', MEMORY_PATH, LOOPS_PATH, DECISIONS_PATH,
    ]));
    expect(fake.notes.get(LOOPS_PATH)).toContain('loop-ship-familiar');
    expect(fake.notes.get('Familiar/briefings/2026-07-08.md')).toContain('type: familiar-briefing');
  });

  it('raises the per-call budget cap above the backend default so an opus sweep at full budget does not get cut off', async () => {
    await runSweep(DEPS(fake.api));
    expect(fake.llmCalls[0].budgetUsd).toBe(5.0);
  });

  it('excludes Familiar/ notes from the delta it sends the model', async () => {
    fake.notes.set(MEMORY_PATH, '# Memory');
    await runSweep(DEPS(fake.api));
    const prompt = fake.llmCalls[0].prompt;
    expect(prompt).not.toContain('<note path="Familiar/');
  });

  it('retries once on parse failure, then succeeds', async () => {
    fake = makeFakeApi({
      llmResponses: [
        { text: 'not json at all', structured: null, error: null },
        { text: '', structured: GOOD_OUTPUT, error: null },
      ],
    });
    fake.notes.set('10-daily/2026-07-07.md', 'x');
    const report = await runSweep(DEPS(fake.api));
    expect(report.ok).toBe(true);
    expect(fake.llmCalls.length).toBe(2);
    expect(fake.llmCalls[1].prompt).toContain('not valid JSON');
  });

  it('fails after second parse failure without touching trackers, exposing raw output', async () => {
    fake = makeFakeApi({ llmResponses: [{ text: 'bad', structured: null, error: null }] });
    fake.notes.set('10-daily/2026-07-07.md', 'x');
    const report = await runSweep(DEPS(fake.api));
    expect(report.ok).toBe(false);
    expect(report.rawOutput).toBe('bad');
    expect(fake.puts).toEqual([]);
  });

  it('user dismissal mid-run survives write-back', async () => {
    // tracker on disk already has the loop dismissed; model returns it open
    fake.notes.set(LOOPS_PATH, renderOpenLoops(
      [{ ...GOOD_OUTPUT.openLoops[0], status: 'dismissed' }], [],
    ));
    fake.notes.set('10-daily/2026-07-07.md', 'x');
    await runSweep(DEPS(fake.api));
    const { loops } = parseOpenLoops(fake.notes.get(LOOPS_PATH));
    expect(loops[0].status).toBe('dismissed');
  });

  it('propagates llm endpoint error', async () => {
    fake = makeFakeApi({ llmResponses: [{ text: '', structured: null, error: 'LLMError: boom' }] });
    fake.notes.set('10-daily/2026-07-07.md', 'x');
    const report = await runSweep(DEPS(fake.api));
    expect(report.ok).toBe(false);
    expect(report.error).toContain('boom');
  });

  it('sends the etag it read as If-Match on every rewrite of an existing note', async () => {
    fake.notes.set(MEMORY_PATH, '# Memory\nold');
    fake.notes.set(LOOPS_PATH, renderOpenLoops([], []));
    fake.notes.set(DECISIONS_PATH, '# Decisions\n');
    fake.notes.set('Familiar/briefings/2026-07-08.md', 'earlier briefing today');
    const before = new Map(fake.notes);
    const report = await runSweep(DEPS(fake.api));
    expect(report.ok).toBe(true);
    expect(fake.puts).toHaveLength(4);
    fake.puts.forEach((put, i) => {
      expect(fake.putOpts[i]).toEqual({ ifMatch: etagOf(before.get(put.path)) });
    });
  });

  it('sends no If-Match when creating a note that does not exist yet', async () => {
    const report = await runSweep(DEPS(fake.api));
    expect(report.ok).toBe(true);
    expect(fake.puts).toHaveLength(4);
    fake.putOpts.forEach((o) => expect(o).toBeUndefined());
  });

  it('a later run sends the etag of what the earlier run wrote', async () => {
    // two sweeps on the same api: the second run reads again, so it sends the etag of what run 1 wrote
    await runSweep(DEPS(fake.api));
    const written = fake.notes.get(MEMORY_PATH);
    fake.puts.length = 0; fake.putOpts.length = 0;
    await runSweep(DEPS(fake.api));
    const i = fake.puts.findIndex((p) => p.path === MEMORY_PATH);
    expect(fake.putOpts[i]).toEqual({ ifMatch: etagOf(written) });
  });

  it.each([
    [409, 'Note changed since it was read'],
    [428, 'If-Match required'],
  ])('reports failure when a rewrite is refused with %i', async (status, error) => {
    fake = makeFakeApi({
      llmResponses: [{ text: '', structured: GOOD_OUTPUT, error: null }],
      putFailure: { ok: false, status, error },
    });
    fake.notes.set('10-daily/2026-07-07.md', 'x');
    fake.notes.set(MEMORY_PATH, '# Memory\nuser edit');
    const report = await runSweep(DEPS(fake.api));
    expect(report.ok).toBe(false);
    expect(report.error).toContain(error);
    expect(fake.notes.get(MEMORY_PATH)).toBe('# Memory\nuser edit');
  });
});
