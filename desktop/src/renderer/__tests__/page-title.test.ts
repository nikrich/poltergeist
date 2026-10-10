import { describe, expect, it } from 'vitest';
import {
  joinPageTitle,
  retitlePage,
  sanitizePageTitle,
  splitPageTitle,
} from '../lib/editor/page-title';

describe('splitPageTitle', () => {
  it('takes a leading H1 as the title for notes and jots', () => {
    for (const rule of ['note', 'jot'] as const) {
      const s = splitPageTitle('# Plan\n\nbody text', rule);
      expect(s).toMatchObject({ title: 'Plan', kind: 'h1', head: '# Plan\n\n', rest: 'body text' });
    }
  });

  it('a note without an H1 owns no title', () => {
    expect(splitPageTitle('hand-written', 'note')).toMatchObject({ title: '', kind: null, head: '', rest: 'hand-written' });
  });

  it('a jot owns a plain first line followed by a blank line or the end', () => {
    expect(splitPageTitle('first jot\n\nfull body here', 'jot')).toMatchObject({
      title: 'first jot', kind: 'plain', head: 'first jot\n\n', rest: 'full body here',
    });
    expect(splitPageTitle('pending content here', 'jot')).toMatchObject({
      title: 'pending content here', kind: 'plain', rest: '',
    });
  });

  it('a jot whose first line runs on into a paragraph owns no title', () => {
    expect(splitPageTitle('line one\nline two', 'jot').kind).toBeNull();
  });

  it.each([
    '- item\n\nx',
    '1. item\n\nx',
    '#tag line\n\nx',
    '## Second level\n\nx',
    '> [!info]\n> x',
    '```js\nconst a = 1;\n```',
    '![](90-meta/assets/a.png)\n\nx',
    '| a | b |\n\nx',
    '[[a note]] is related\n\nx',
    'see [the docs](https://a.example)\n\nx',
    '**bold** opener\n\nx',
    'run `make` first\n\nx',
    '---\n\nx',
    'x'.repeat(121) + '\n\nbody',
  ])('a jot never takes %j as its title', (body) => {
    expect(splitPageTitle(body, 'jot').kind).toBeNull();
  });

  it('strips an ATX closing sequence and unescapes a trailing \\#', () => {
    expect(splitPageTitle('# Title ##\n\nx', 'note').title).toBe('Title');
    expect(splitPageTitle('# Issue \\#\n\nx', 'note').title).toBe('Issue #');
  });

  it('an empty H1 owns no title', () => {
    expect(splitPageTitle('# \n\nx', 'note').kind).toBeNull();
    expect(splitPageTitle('#\n\nx', 'note').kind).toBeNull();
  });
});

describe('joinPageTitle round-trips byte for byte', () => {
  it.each([
    ['h1 + blank + body', '# Plan\n\nbody text', 'note'],
    ['h1 straight into text', '# T\nbody', 'note'],
    ['crlf', '# T\r\n\r\nbody\r\n', 'note'],
    ['leading blank lines', '\n\n# T\n\nx', 'note'],
    ['no-title note', 'hand-written', 'note'],
    ['jot plain title', 'first jot\n\nfull body here', 'jot'],
    ['title-only jot', 'pending content here', 'jot'],
    ['new jot default', 'new jot\n\n', 'jot'],
    ['h1 only, trailing newline', '# Only\n', 'note'],
  ] as const)('%s', (_name, body, rule) => {
    const s = splitPageTitle(body, rule);
    expect(joinPageTitle(s, s.rest)).toBe(body);
  });

  it('puts a blank line between a title line at EOF and new body text', () => {
    const plain = splitPageTitle('pending content here', 'jot');
    expect(joinPageTitle(plain, 'more')).toBe('pending content here\n\nmore');
    const h1 = splitPageTitle('# Only', 'note');
    expect(joinPageTitle(h1, 'more')).toBe('# Only\n\nmore');
  });

  it('keeps the title line when the body is emptied', () => {
    const s = splitPageTitle('# Plan\n\nbody', 'note');
    expect(joinPageTitle(s, '')).toBe('# Plan\n\n');
  });
});

describe('retitlePage', () => {
  it('rewrites an H1 title and keeps everything around it', () => {
    const s = splitPageTitle('# Plan\n\nbody', 'note');
    expect(joinPageTitle(retitlePage(s, 'Launch plan')!, 'body')).toBe('# Launch plan\n\nbody');
  });

  it('keeps a plain jot title plain', () => {
    const s = splitPageTitle('first jot\n\nx', 'jot');
    const next = retitlePage(s, 'Sprint retro')!;
    expect(next.kind).toBe('plain');
    expect(joinPageTitle(next, 'x')).toBe('Sprint retro\n\nx');
  });

  it('promotes a plain title to an H1 when the new text would read as markdown', () => {
    const s = splitPageTitle('first jot\n\nx', 'jot');
    expect(joinPageTitle(retitlePage(s, '- not a list')!, 'x')).toBe('# - not a list\n\nx');
  });

  it('writes a new H1 above a body that owned no title', () => {
    const s = splitPageTitle('hand-written', 'note');
    expect(joinPageTitle(retitlePage(s, 'Spec')!, 'hand-written')).toBe('# Spec\n\nhand-written');
  });

  it('keeps CRLF', () => {
    const s = splitPageTitle('# T\r\n\r\nbody', 'note');
    expect(joinPageTitle(retitlePage(s, 'U')!, 'body')).toBe('# U\r\n\r\nbody');
  });

  it('escapes a trailing # so it is not read as a closing sequence', () => {
    const s = splitPageTitle('# Plan\n\nx', 'note');
    const next = retitlePage(s, 'Issue #')!;
    expect(joinPageTitle(next, 'x')).toBe('# Issue \\#\n\nx');
    expect(splitPageTitle(joinPageTitle(next, 'x'), 'note').title).toBe('Issue #');
  });

  it('returns null for an unchanged, blank or whitespace-only title', () => {
    const s = splitPageTitle('# Plan\n\nx', 'note');
    expect(retitlePage(s, 'Plan')).toBeNull();
    expect(retitlePage(s, '  Plan  ')).toBeNull();
    expect(retitlePage(s, '   ')).toBeNull();
  });
});

describe('sanitizePageTitle', () => {
  it('collapses whitespace and line breaks, trims, caps at 200', () => {
    expect(sanitizePageTitle('  A \n\t B  ')).toBe('A B');
    expect(sanitizePageTitle('x'.repeat(250))).toHaveLength(200);
  });
});
