import { describe, expect, it } from 'vitest';
import {
  DEFAULT_META, draftKey, freeScriptPath, fromFountain, normalizeMeta, parseScriptPath,
  scriptPath, serializeFile, slugify, toFountain, uniqueSlug,
} from '../document.js';

describe('meta + file', () => {
  it('normalises frontmatter, coercing types and defaulting missing keys', () => {
    const m = normalizeMeta({ title: 'Night', scene_numbers: 'yes', draft_date: 20260930, extra: 1 });
    expect(m).toEqual({ ...DEFAULT_META, title: 'Night', scene_numbers: true, draft_date: '20260930' });
  });

  it('serialises frontmatter as YAML-safe JSON strings with the body after it', () => {
    const out = serializeFile({ title: 'He said "hi": ok', scene_numbers: false }, '\n\nFADE IN:');
    expect(out).toBe([
      '---', 'type: screenplay', 'title: "He said \\"hi\\": ok"', 'credit: "Written by"', 'author: ""',
      'source: ""', 'draft_date: ""', 'contact: ""', 'scene_numbers: false', 'updated: ""', '---', 'FADE IN:',
    ].join('\n'));
  });
});

describe('Fountain title page', () => {
  it('writes a title page from meta, with multi-line values indented', () => {
    const out = toFountain({ title: 'Night', author: 'J R', contact: 'a@b.c\n555 1234' }, 'FADE IN:');
    expect(out).toBe('Title: Night\nCredit: Written by\nAuthor: J R\nContact:\n    a@b.c\n    555 1234\n\nFADE IN:');
  });

  it('round-trips through fromFountain', () => {
    const meta = { ...DEFAULT_META, title: 'Night', author: 'J R', contact: 'a@b.c\n555 1234', draft_date: '2026-09-30' };
    const { meta: back, body } = fromFountain(toFountain(meta, 'INT. A - DAY\n\nGo.'));
    expect(back).toEqual(meta);
    expect(body).toBe('INT. A - DAY\n\nGo.');
  });

  it('does not treat FADE IN: as a title page', () => {
    const r = fromFountain('FADE IN:\n\nINT. A - DAY');
    expect(r.meta).toEqual(DEFAULT_META);
    expect(r.body).toBe('FADE IN:\n\nINT. A - DAY');
  });

  it('handles CRLF and Authors alias', () => {
    const r = fromFountain('Title: X\r\nAuthors: Y\r\n\r\nGo.');
    expect(r.meta).toMatchObject({ title: 'X', author: 'Y' });
    expect(r.body).toBe('Go.');
  });
});

describe('slugs + paths', () => {
  it('slugifies titles', () => {
    expect(slugify('The Long Night!')).toBe('the-long-night');
    expect(slugify('Café  Noir')).toBe('cafe-noir');
    expect(slugify('***')).toBe('untitled');
  });

  it('dedupes slugs', () => {
    expect(uniqueSlug('a', new Set(['a', 'a-2']))).toBe('a-3');
  });

  it('builds and parses script paths', () => {
    const p = scriptPath('personal', 'long-night', 'draft');
    expect(p).toBe('20-contexts/personal/projects/long-night/draft.screenplay.md');
    expect(parseScriptPath(p)).toEqual({ context: 'personal', project: 'long-night', slug: 'draft' });
    expect(parseScriptPath('10-daily/x.md')).toBeNull();
  });

  it('derives filesystem-safe draft keys', () => {
    expect(draftKey('20-contexts/personal/projects/long-night/draft.screenplay.md'))
      .toBe('20-contexts-personal-projects-long-night-draft-screenplay-md');
  });

  it('never picks a path that already exists', async () => {
    const existing = new Set([
      '20-contexts/personal/projects/p/night.screenplay.md',
      '20-contexts/personal/projects/p/night-2.screenplay.md',
    ]);
    const path = await freeScriptPath({ context: 'personal', project: 'p', title: 'Night', exists: async (x) => existing.has(x) });
    expect(path).toBe('20-contexts/personal/projects/p/night-3.screenplay.md');
  });
});
