import { describe, expect, it } from 'vitest';
import { parse, isUpperCue } from '../parse.js';

const types = (s) => parse(s).map((e) => e.type);

describe('parse', () => {
  it('parses a scene heading, action, and a dialogue block', () => {
    const els = parse('INT. LIGHTHOUSE - NIGHT\n\nRain hammers the glass.\n\nMARA\n(quietly)\nIt found us.\nAgain.\n');
    expect(els.map((e) => e.type)).toEqual(['scene_heading', 'action', 'character', 'parenthetical', 'dialogue']);
    expect(els[0]).toMatchObject({ text: 'INT. LIGHTHOUSE - NIGHT', line: 0, lineEnd: 0 });
    expect(els[4]).toMatchObject({ text: 'It found us.\nAgain.', line: 6, lineEnd: 7 });
  });

  it('recognises all scene prefixes case-insensitively and forced headings', () => {
    expect(types('ext. beach - day')).toEqual(['scene_heading']);
    expect(types('INT./EXT. CAR - MOVING')).toEqual(['scene_heading']);
    expect(types('I/E. HALLWAY')).toEqual(['scene_heading']);
    expect(parse('.FLASHBACK')[0]).toMatchObject({ type: 'scene_heading', text: 'FLASHBACK' });
    expect(types('..not a heading')).toEqual(['action']);
  });

  it('extracts scene numbers', () => {
    expect(parse('INT. HOUSE - DAY #12A#')[0]).toMatchObject({ text: 'INT. HOUSE - DAY', sceneNumber: '12A' });
  });

  it('accepts a scene heading with no blank line after it', () => {
    expect(types('INT. HOUSE - DAY\nMara enters.')).toEqual(['scene_heading', 'action']);
  });

  it('treats an all-caps line followed by a blank as action, not a character', () => {
    expect(types('BANG!\n\nThe door explodes.')).toEqual(['action', 'action']);
  });

  it('treats an all-caps line followed by text as a character cue', () => {
    expect(types('BANG!\nThe door explodes.')).toEqual(['character', 'dialogue']);
  });

  it('keeps character extensions and handles forced/lowercase-extension cues', () => {
    expect(parse('MARA (V.O.)\nHello.')[0]).toMatchObject({ type: 'character', text: 'MARA (V.O.)' });
    expect(parse("MARA (cont'd)\nHello.")[0].type).toBe('character');
    expect(parse('@McCLANE\nYippee.')[0]).toMatchObject({ type: 'character', text: 'McCLANE' });
  });

  it('parses transitions: auto TO: and forced >', () => {
    expect(types('Action.\n\nCUT TO:\n\nINT. X - DAY')).toEqual(['action', 'transition', 'scene_heading']);
    expect(parse('> FADE OUT.')[0]).toMatchObject({ type: 'transition', text: 'FADE OUT.' });
    expect(types('Action.\n\nSMASH CUT TO:\nMore action.')).toEqual(['action', 'character', 'dialogue']);
  });

  it('parses centered, lyric, page break, section, synopsis, note and boneyard', () => {
    const els = parse('>THE END<\n\n~Sing it\n\n===\n\n## Act Two\n\n= She finds the key.\n\n[[fix this]]\n\n/* old\nscene */');
    expect(els.map((e) => e.type)).toEqual(['centered', 'lyric', 'page_break', 'section', 'synopsis', 'note', 'boneyard']);
    expect(els[0].text).toBe('THE END');
    expect(els[3]).toMatchObject({ text: 'Act Two', depth: 2 });
    expect(els[4].text).toBe('She finds the key.');
    expect(els[5].text).toBe('fix this');
    expect(els[6]).toMatchObject({ line: 12, lineEnd: 13 });
  });

  it('strips forced-action markers', () => {
    expect(parse('!SCREAMS FROM BELOW\nMore.')[0]).toMatchObject({ type: 'action', text: 'SCREAMS FROM BELOW\nMore.' });
  });

  it('marks dual dialogue', () => {
    const els = parse('BRICK\nScrew retirement.\n\nSTEEL ^\nScrew retirement.');
    expect(els[0]).toMatchObject({ type: 'character', dual: 'left' });
    expect(els[2]).toMatchObject({ type: 'character', text: 'STEEL', dual: 'right' });
  });

  it('keeps two-space lines inside dialogue', () => {
    const els = parse('MARA\nLine one.\n  \nLine two.');
    expect(els.map((e) => e.type)).toEqual(['character', 'dialogue']);
    expect(els[1].lineEnd).toBe(3);
  });

  it('normalises CRLF', () => {
    expect(types('INT. A - DAY\r\n\r\nAction.')).toEqual(['scene_heading', 'action']);
  });

  it('parses a 10k-line script quickly', () => {
    const block = 'INT. ROOM - DAY\n\nShe waits by the window, counting.\n\nMARA\n(beat)\nNot yet.\n\n';
    const big = block.repeat(1250); // 10,000 lines
    const t0 = performance.now();
    const els = parse(big);
    expect(performance.now() - t0).toBeLessThan(200);
    expect(els.length).toBe(1250 * 5);
  });
});

describe('isUpperCue', () => {
  it('ignores the parenthetical extension and dual marker', () => {
    expect(isUpperCue("MARA (cont'd)")).toBe(true);
    expect(isUpperCue('MARA ^')).toBe(true);
    expect(isUpperCue('Mara')).toBe(false);
    expect(isUpperCue('123')).toBe(false);
  });
});
