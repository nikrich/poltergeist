import { describe, expect, it } from 'vitest';
import { pageAuthor, pageBreadcrumb, pageUpdated, titleRuleFor } from '../lib/page-meta';

describe('pageBreadcrumb', () => {
  it.each([
    ['20-contexts/work/notes/x.md', { context: 'work', project: 'payments' }, ['work', 'payments']],
    ['20-contexts/work/notes/x.md', {}, ['work']],
    ['00-inbox/raw/manual/x.md', { context: null }, ['inbox']],
    ['00-inbox/raw/manual/x.md', { context: 'personal' }, ['personal']],
    ['10-daily/2026/10/2026-10-10.md', {}, ['daily', '2026', '10']],
    ['x.md', undefined, []],
  ] as const)('%s → %j', (path, fm, expected) => {
    expect(pageBreadcrumb(path, fm as Record<string, unknown> | undefined)).toEqual(expected);
  });
});

describe('pageAuthor', () => {
  it.each([
    [{ author: 'ops-bot' }, 'ops-bot'],
    [{ source: 'manual' }, 'you'],
    [{ source: 'chat-summary' }, 'you'],
    [{}, 'you'],
    [undefined, 'you'],
    [{ source: 'gmail' }, 'gmail'],
    [{ author: ['a', 'b'], source: 'slack' }, 'slack'],
  ] as const)('%j → %s', (fm, expected) => {
    expect(pageAuthor(fm as Record<string, unknown> | undefined)).toBe(expected);
  });
});

describe('pageUpdated', () => {
  it('prefers updated, then created, then ingestedAt', () => {
    expect(pageUpdated({ updated: '2026-10-10T08:00:00Z', created: '2026-10-01T08:00:00Z' })).toBe('2026-10-10T08:00:00Z');
    expect(pageUpdated({ created: '2026-10-01T08:00:00Z' })).toBe('2026-10-01T08:00:00Z');
    expect(pageUpdated({ ingestedAt: '2026-09-01T08:00:00Z' })).toBe('2026-09-01T08:00:00Z');
    expect(pageUpdated({})).toBeNull();
    expect(pageUpdated(undefined)).toBeNull();
  });
});

describe('titleRuleFor', () => {
  it('jots and chat summaries use the jot rule; everything else the note rule', () => {
    expect(titleRuleFor({ source: 'manual' })).toBe('jot');
    expect(titleRuleFor({ source: 'chat-summary' })).toBe('jot');
    expect(titleRuleFor({ source: 'gmail' })).toBe('note');
    expect(titleRuleFor(undefined)).toBe('note');
  });
});
