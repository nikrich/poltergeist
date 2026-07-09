import { describe, expect, it } from 'vitest';
import { splitBriefingSections, ageDays, sectionIcon, historyFromRuns } from '../briefing.js';

const MD = `# Weekly Briefing — 2026-07-01 → 2026-07-08

*Coverage note: partial.*

## Themes

- **Claims path works.** Details here.

## Open loops (notable)

- loop one

## Decisions

- decided X

## Contradictions

- said A did B

## Blind spots

- nobody checked on-call load
`;

describe('splitBriefingSections', () => {
  it('splits preamble and h2 sections', () => {
    const { preamble, sections } = splitBriefingSections(MD);
    expect(preamble).toContain('Coverage note');
    expect(sections.map((s) => s.title)).toEqual([
      'Themes', 'Open loops (notable)', 'Decisions', 'Contradictions', 'Blind spots',
    ]);
    expect(sections[0].body).toContain('Claims path works');
  });
  it('handles a briefing with no h2 sections', () => {
    const { preamble, sections } = splitBriefingSections('just some text\nwith lines');
    expect(sections).toEqual([]);
    expect(preamble).toContain('just some text');
  });
  it('ignores ## inside code fences', () => {
    const md = 'intro\n\n```\n## not a heading\n```\n\n## Real\n\nbody';
    const { sections } = splitBriefingSections(md);
    expect(sections.map((s) => s.title)).toEqual(['Real']);
  });
});

describe('ageDays', () => {
  it('computes whole days since firstSeen', () => {
    expect(ageDays('2026-07-01', new Date(2026, 6, 9, 12, 0))).toBe(8);
    expect(ageDays('2026-07-09', new Date(2026, 6, 9, 12, 0))).toBe(0);
  });
  it('returns null for garbage', () => {
    expect(ageDays('not-a-date', new Date())).toBe(null);
  });
});

describe('sectionIcon', () => {
  it('maps known section titles to icons', () => {
    expect(sectionIcon('Themes')).toBe('target');
    expect(sectionIcon('Open loops (notable)')).toBe('repeat');
    expect(sectionIcon('Blind spots')).toBe('eye-off');
    expect(sectionIcon('Something new')).toBe('sparkles');
  });
});

describe('historyFromRuns', () => {
  it('keeps ok runs with briefings, newest first, deduped by path', () => {
    const runs = [
      { ok: true, briefingPath: 'Familiar/briefings/2026-07-01.md', finishedAt: '2026-07-01T07:05:00Z', noteCount: 40, costUsd: 0.8 },
      { ok: false, error: 'boom', finishedAt: '2026-07-05T07:05:00Z' },
      { ok: true, briefingPath: 'Familiar/briefings/2026-07-08.md', finishedAt: '2026-07-08T12:16:00Z', noteCount: 110, costUsd: 1.05 },
      { ok: true, briefingPath: 'Familiar/briefings/2026-07-08.md', finishedAt: '2026-07-08T14:16:00Z', noteCount: 112, costUsd: 1.1 },
    ];
    const h = historyFromRuns(runs);
    expect(h.map((x) => x.path)).toEqual([
      'Familiar/briefings/2026-07-08.md', 'Familiar/briefings/2026-07-01.md',
    ]);
    expect(h[0].noteCount).toBe(112);
    expect(h[0].date).toBe('2026-07-08');
  });
});
