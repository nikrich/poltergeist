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

  it('text containing " — owed to " does not corrupt owedTo when owedTo is null', () => {
    const loop = {
      id: 'loop-owed-embed',
      text: 'Tell them — owed to nobody about the delay',
      owedTo: null,
      sourcePath: 'real.md',
      firstSeen: '2024-01-01',
      status: 'open',
    };
    const { loops } = parseOpenLoops(renderOpenLoops([loop], []));
    expect(loops).toEqual([{ ...loop, text: 'Tell them - owed to nobody about the delay' }]);
  });

  it('text containing "(from [source](" does not corrupt sourcePath or truncate text', () => {
    const loop = {
      id: 'loop-source-embed',
      text: 'Send report (from [source](inner.md), first seen 2020-01-01) done',
      owedTo: null,
      sourcePath: 'real.md',
      firstSeen: '2024-01-01',
      status: 'open',
    };
    const { loops } = parseOpenLoops(renderOpenLoops([loop], []));
    expect(loops).toEqual([{
      ...loop,
      text: 'Send report (from [source] (inner.md), first seen 2020-01-01) done',
    }]);
  });

  it('preserves fixed fields exactly and free-text fields up to sanitization', () => {
    const loop = {
      id: 'loop-mixed',
      text: 'Ping — owed to someone (from [source](embedded.md), first seen 2019-01-01) after',
      owedTo: 'Alex — the reviewer',
      sourcePath: 'real.md',
      firstSeen: '2024-01-01',
      status: 'open',
    };
    const sanitize = (s) => s
      .replace(/ — owed to /g, ' - owed to ')
      .replace(/\(from \[source\]\(/g, '(from [source] (');
    const { loops } = parseOpenLoops(renderOpenLoops([loop], []));
    expect(loops).toHaveLength(1);
    const [parsed] = loops;
    expect(parsed.id).toBe(loop.id);
    expect(parsed.sourcePath).toBe(loop.sourcePath);
    expect(parsed.firstSeen).toBe(loop.firstSeen);
    expect(parsed.status).toBe(loop.status);
    expect(parsed.text).toBe(sanitize(loop.text));
    expect(parsed.owedTo).toBe(sanitize(loop.owedTo));
  });
});

describe('newline sanitization', () => {
  it('a loop whose text contains embedded newlines round-trips to a single-line entry, preserving id/status', () => {
    const loop = {
      id: 'loop-multiline',
      text: 'Follow up with\nAlex about the\n  proposal',
      owedTo: null,
      sourcePath: 'a.md',
      firstSeen: '2026-07-01',
      status: 'open',
    };
    const md = renderOpenLoops([loop], []);
    // exactly one list-item line for this loop — no stray continuation lines
    const itemLines = md.split('\n').filter((l) => l.startsWith('- ['));
    expect(itemLines).toHaveLength(1);
    const { loops } = parseOpenLoops(md);
    expect(loops).toHaveLength(1);
    expect(loops[0].id).toBe('loop-multiline');
    expect(loops[0].status).toBe('open');
    expect(loops[0].text).toBe('Follow up with Alex about the proposal');
  });

  it('a decision with embedded newlines survives render→parse as a single line', () => {
    const dec = { date: '2026-07-01', text: 'Chose plugin\narchitecture\nover monolith', sourcePath: 'a.md' };
    const md = renderDecisions([dec]);
    const itemLines = md.split('\n').filter((l) => l.startsWith('- '));
    expect(itemLines).toHaveLength(1);
    const parsed = parseDecisions(md);
    expect(parsed).toEqual([{ ...dec, text: 'Chose plugin architecture over monolith' }]);
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
  it('text containing "(from [source](" does not corrupt sourcePath', () => {
    const dec = {
      date: '2026-07-01',
      text: 'Approved (from [source](old.md), first seen 2020-01-01) after review',
      sourcePath: 'real.md',
    };
    const parsed = parseDecisions(renderDecisions([dec]));
    expect(parsed).toEqual([{
      ...dec,
      text: 'Approved (from [source] (old.md), first seen 2020-01-01) after review',
    }]);
  });
  it('merge appends new, dedups by date+text', () => {
    const merged = mergeDecisions([DEC], [DEC, { ...DEC, text: 'Another' }]);
    expect(merged.length).toBe(2);
  });

  it('sanitizes model-decision text before computing the dedup key, so a re-emitted delimiter-bearing decision does not duplicate every run', () => {
    // Simulate a decision already on disk: written once via renderDecisions
    // (which sanitizes), then read back via parseDecisions — so its stored
    // text is the sanitized form.
    const rawText = 'Approved (from [source](old.md), first seen 2020-01-01) after review';
    const onDisk = parseDecisions(renderDecisions([{ date: '2026-07-01', text: rawText, sourcePath: 'real.md' }]));
    // The model re-emits the SAME decision, unsanitized, on the next sweep.
    const fromModel = [{ date: '2026-07-01', text: rawText, sourcePath: 'real.md' }];
    const merged = mergeDecisions(onDisk, fromModel);
    expect(merged.length).toBe(1);
  });
});
