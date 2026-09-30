// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { parse } from '../../fountain/parse.js';
import { fountainLine, fromFdx } from '../import.js';
import { toFdx } from '../export.js';

const BODY = 'INT. LIGHTHOUSE - NIGHT\n\nRain **hammers** the glass.\n\nMARA\n(quietly)\nIt found us.\n\nBRICK\nScrew it.\n\nSTEEL ^\nScrew it.\n\nCUT TO:\n\n>THE END<\n';
const kinds = (b) => parse(b).map((e) => [e.type, e.dual ?? null]);

describe('fdx', () => {
  it('exports typed paragraphs, styles, dual dialogue and a title page', () => {
    const xml = toFdx({ title: 'The Long Night', author: 'J R' }, BODY);
    expect(xml.startsWith('<?xml')).toBe(true);
    expect(xml).toContain('<Paragraph Type="Scene Heading">');
    expect(xml).toContain('<Text Style="Bold">hammers</Text>');
    expect(xml).toContain('<DualDialogue>');
    expect(xml).toContain('<Paragraph Type="Action" Alignment="Center">');
    expect(xml).toContain('<TitlePage>');
    expect(xml).toContain('The Long Night');
  });
  it('round-trips element types, emphasis and title', () => {
    const { meta, body } = fromFdx(toFdx({ title: 'The Long Night' }, BODY));
    expect(meta.title).toBe('The Long Night');
    expect(kinds(body)).toEqual(kinds(BODY));
    expect(body).toContain('**hammers**');
    expect(body).toContain('>THE END<');
  });
  it('escapes XML and rejects non-FDX input', () => {
    expect(toFdx({}, 'Tom & Jerry <3')).toContain('Tom &amp; Jerry &lt;3');
    expect(() => fromFdx('<html></html>')).toThrow('Not a Final Draft (.fdx) file');
    expect(() => fromFdx('not xml at all <')).toThrow('Not a Final Draft (.fdx) file');
  });

  const wrap = (paras) => `<?xml version="1.0"?><FinalDraft><Content>${paras}</Content></FinalDraft>`;
  const P = (type, text) => `<Paragraph Type="${type}"><Text>${text}</Text></Paragraph>`;
  const els = (xml) => parse(fromFdx(xml).body);

  it('preserves text that looks like Fountain markup', () => {
    const e = els(wrap(P('Action', '.45 caliber rounds') + P('Action', '# Act One') + P('Action', '===') + P('Action', 'BANG!')
      + P('Character', 'MARA') + P('Dialogue', '!?')));
    expect(e.filter((x) => x.type === 'action').map((x) => x.text)).toEqual(['.45 caliber rounds', '# Act One', '===', 'BANG!']);
    expect(e.find((x) => x.type === 'dialogue').text).toBe('!?');
  });
  it('keeps literal * and _ through import', () => {
    const e = els(wrap(P('Action', '5 * 3 = 15_x')));
    expect(e[0].type).toBe('action');
    expect(e[0].text.replace(/\\([*_])/g, '$1')).toBe('5 * 3 = 15_x');
  });
  it('decodes XML entities on import', () => {
    const { body } = fromFdx(wrap(P('Action', 'Tom &amp; Jerry &lt;3 &quot;hi&quot;')));
    expect(body).toContain('Tom & Jerry <3 "hi"');
  });
  it('fountainLine forces each element type', () => {
    expect(fountainLine('scene_heading', 'int. a - day')).toBe('INT. A - DAY');
    expect(fountainLine('scene_heading', 'the woods')).toBe('.THE WOODS');
    expect(fountainLine('character', 'mara')).toBe('MARA');
    expect(fountainLine('character', 'mara (v.o.)')).toBe('MARA (V.O.)');
    expect(fountainLine('character', '!?')).toBe('@!?');
    expect(fountainLine('transition', 'cut to:')).toBe('CUT TO:');
    expect(fountainLine('transition', 'fade out')).toBe('>FADE OUT');
    expect(fountainLine('parenthetical', 'beat')).toBe('(beat)');
    expect(fountainLine('parenthetical', '(beat)')).toBe('(beat)');
    expect(fountainLine('dialogue', 'a\n \t\nb')).toBe('a\nb');
    expect(fountainLine('action', 'plain')).toBe('plain');
    expect(fountainLine('action', '.45')).toBe('!.45');
    expect(fountainLine('action', 'BANG')).toBe('!BANG');
    expect(fountainLine('action', 'INT. HOUSE')).toBe('!INT. HOUSE');
    expect(fountainLine('action', '=== x')).toBe('!=== x');
  });
  it('keeps multi-line actions as one action', () => {
    const one = (t) => els(wrap(P('Action', t)));
    for (const t of ['BANG!\nThe door opens.', 'Wow\n!?', 'INT. HOUSE\nis dark']) {
      const e = one(t);
      expect(e.map((x) => x.type)).toEqual(['action']);
      expect(e[0].text).toBe(t);
    }
  });
});
