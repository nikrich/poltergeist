// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { parse } from '../../fountain/parse.js';
import { fromFdx } from '../import.js';
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
});
