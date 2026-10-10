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

describe('pathological first lines parse in linear time (no ReDoS)', () => {
  /** Warm the JIT on the same call, then time a second run. */
  const elapsed = (fn: () => unknown): number => {
    fn();
    const t0 = performance.now();
    fn();
    return performance.now() - t0;
  };
  // Linear runs take ~1ms; quadratic ones take seconds. 500 leaves room for
  // slow Windows release runners without hiding a regression.
  const BOUND_MS = 500;
  const spaces = ' '.repeat(100_000);
  const nearCap = (unit: string, end: string) =>
    unit.repeat(Math.floor((1_999 - 2 - end.length) / unit.length)) + end;

  it.each([
    ['long space run before a non-space', '# a' + spaces + 'b'],
    ['many " #" pairs', '# ' + ' #'.repeat(50_000) + 'x'],
    ['space runs between # runs', '# a' + (' '.repeat(50) + '#').repeat(2_000) + 'b'],
    ['long backslash run', '# ' + '\\'.repeat(100_000) + '#'],
    ['spaces then tabs', '# a' + ' \t'.repeat(50_000) + 'b'],
    ['near-cap space run', '# a' + ' '.repeat(1_990) + 'b'],
    ['near-cap " #" pairs', '# ' + nearCap(' #', 'x')],
    ['near-cap spaces + # runs', '# ' + nearCap('  ##', 'x')],
    ['near-cap backslashes', '# ' + nearCap('\\', '#')],
    ['near-cap list-ish', nearCap('- ', 'x')],
    ['long list-ish', '- '.repeat(50_000) + 'x'],
    ['long thematic-ish', '-  '.repeat(33_000) + 'x'],
    ['long ===', '='.repeat(100_000) + 'x'],
  ])('splitPageTitle: %s', (_name, line) => {
    for (const rule of ['note', 'jot'] as const) {
      for (const body of [line, line + '\n\nbody']) {
        expect(elapsed(() => splitPageTitle(body, rule))).toBeLessThan(BOUND_MS);
      }
    }
  });

  it.each([
    ['h1 at EOF after a long blank-ish lead', spaces + '\n# T', 'note'],
    ['plain jot title at EOF after a long blank-ish lead', spaces + '\nfirst jot', 'jot'],
    ['h1 then a long whitespace tail', '# T\n' + spaces, 'note'],
    ['tab/space lead lines', ' \t'.repeat(50_000) + '\n# T', 'note'],
  ] as const)('joinPageTitle / retitlePage: %s', (_name, body, rule) => {
    const s = splitPageTitle(body, rule);
    expect(s.kind).not.toBeNull();
    expect(elapsed(() => joinPageTitle(s, 'more'))).toBeLessThan(BOUND_MS);
    expect(elapsed(() => joinPageTitle(s, s.rest))).toBeLessThan(BOUND_MS);
    expect(elapsed(() => retitlePage(s, 'Renamed #'))).toBeLessThan(BOUND_MS);
  });

  it('retitlePage / sanitizePageTitle on a huge pasted title', () => {
    const s = splitPageTitle('# Plan\n\nx', 'note');
    for (const raw of [' '.repeat(100_000) + 'x', 'a ' + '#'.repeat(100_000), '\\'.repeat(100_000) + '#']) {
      expect(elapsed(() => retitlePage(s, raw))).toBeLessThan(BOUND_MS);
    }
  });

  it('a first line longer than 2,000 chars owns no title but round-trips', () => {
    for (const rule of ['note', 'jot'] as const) {
      const body = '# ' + 'x'.repeat(2_000) + '\n\nbody';
      const s = splitPageTitle(body, rule);
      expect(s.kind).toBeNull();
      expect(joinPageTitle(s, s.rest)).toBe(body);
    }
    expect(splitPageTitle('# ' + 'x'.repeat(1_990) + '\n\nbody', 'note').kind).toBe('h1');
  });

  it.each([
    ['exactly 2,000 chars is still scanned', 1_998, 'h1'],
    ['2,001 chars is past the cap', 1_999, null],
  ] as const)('cap boundary: %s', (_name, n, kind) => {
    const line = '# ' + 'x'.repeat(n);
    expect(line.length).toBe(n + 2);
    const body = line + '\n\nbody';
    const s = splitPageTitle(body, 'note');
    expect(s.kind).toBe(kind);
    expect(joinPageTitle(s, s.rest)).toBe(body);
  });
});

describe('Task 2 review fixes', () => {
  it('# # (only a closing sequence) is an empty heading and owns no title', () => {
    expect(splitPageTitle('# #\n\nx', 'note').kind).toBeNull();
    expect(splitPageTitle('# ###\n\nx', 'jot').kind).toBeNull();
    expect(splitPageTitle('#  #  \n\nx', 'note').kind).toBeNull();
  });

  it.each([
    ['h1 + whitespace-only rest', '# T\n\n ', 'note'],
    ['jot + whitespace-only rest', 'title\n\t', 'jot'],
    ['jot crlf', 't\r\n\r\nbody\r\n', 'jot'],
    ['jot leading blank lines', '\n\n  \nfirst jot\n\nbody', 'jot'],
  ] as const)('round-trips %s byte for byte', (_name, body, rule) => {
    const s = splitPageTitle(body, rule);
    expect(s.kind).not.toBeNull();
    expect(joinPageTitle(s, s.rest)).toBe(body);
  });

  it('an emptied body still keeps just the head', () => {
    const s = splitPageTitle('# T\n\n ', 'note');
    expect(joinPageTitle(s, '')).toBe('# T\n\n');
  });

  it.each(['    code\n\nx', '\tcode\n\nx', '  \tcode\n\nx'])(
    'an indented code block %j is not a jot title',
    (body) => {
      expect(splitPageTitle(body, 'jot').kind).toBeNull();
    },
  );

  it.each(['Issue #', 'C\\#', '#', '##', 'C#', 'a \\\\##', 'x \\'])(
    'retitle -> join -> split round-trips %j',
    (title) => {
      for (const [body, rule] of [['# Plan\n\nx', 'note'], ['first jot\n\nx', 'jot'], ['plain', 'note']] as const) {
        const next = retitlePage(splitPageTitle(body, rule), title)!;
        expect(next.title).toBe(title);
        const saved = joinPageTitle(next, next.rest);
        expect(splitPageTitle(saved, rule)).toMatchObject({ title, kind: next.kind });
      }
    },
  );

  it('sanitizePageTitle never splits a surrogate pair at the cap', () => {
    const out = sanitizePageTitle('x'.repeat(199) + '\u{1F600}' + 'tail');
    expect(Array.from(out)).toHaveLength(200);
    expect(out.endsWith('\u{1F600}')).toBe(true);
    expect(sanitizePageTitle('x'.repeat(199) + ' y')).toBe('x'.repeat(199));
  });
});
