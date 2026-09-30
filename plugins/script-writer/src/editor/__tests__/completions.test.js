import { describe, expect, it } from 'vitest';
import { parse } from '../../fountain/parse.js';
import { completionsFor, locations } from '../completions.js';
import { scriptCompletions } from '../complete.js';

const els = parse('INT. LIGHTHOUSE - NIGHT\n\nMARA\nHi.\n\nEXT. BEACH - DAY\n\nJOE\nYo.\n\nMARA\nAgain.\n\nINT. LIGHTHOUSE - DAY\n\nGo.');
const c = (text, type = 'action', prevBlank = true) => completionsFor({ text, type, prevBlank, elements: els });

describe('completions', () => {
  it('ranks locations by use', () => {
    expect(locations(els)).toEqual(['LIGHTHOUSE', 'BEACH']);
  });
  it('offers scene prefixes for a short start on a fresh line', () => {
    expect(c('in')).toEqual({ from: 0, options: ['INT. ', 'INT./EXT. '] });
    expect(c('INT.')).toEqual({ from: 0, options: ['INT. ', 'INT./EXT. '] });
  });
  it('offers known locations after the prefix', () => {
    expect(c('INT. LI', 'scene_heading')).toEqual({ from: 5, options: ['LIGHTHOUSE'] });
  });
  it('offers times after " - "', () => {
    expect(c('INT. LIGHTHOUSE - N', 'scene_heading')).toEqual({ from: 18, options: ['NIGHT'] });
  });
  it('offers character names by frequency', () => {
    expect(c('', 'character')).toEqual({ from: 0, options: ['MARA', 'JOE'] });
    expect(c('J', 'character')).toEqual({ from: 0, options: ['JOE'] });
  });
  it('offers extensions after (', () => {
    expect(c('MARA (', 'character').options).toEqual(['(V.O.)', '(O.S.)', "(CONT'D)", '(O.C.)']);
    expect(c('MARA (V', 'character')).toEqual({ from: 5, options: ['(V.O.)'] });
  });
  it('offers nothing inside dialogue or mid-paragraph', () => {
    expect(c('hel', 'dialogue', false)).toBeNull();
    expect(c('She walks', 'action', false)).toBeNull();
  });
});
