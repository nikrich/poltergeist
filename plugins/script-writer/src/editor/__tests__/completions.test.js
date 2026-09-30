import { describe, expect, it } from 'vitest';
import { parse } from '../../fountain/parse.js';
import { completionsFor, locations } from '../completions.js';
import { scriptCompletions, scriptCompletionSource } from '../complete.js';
import { EditorState } from '@codemirror/state';
import { CompletionContext } from '@codemirror/autocomplete';
import { analysisField } from '../analysis.js';

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
  it('never throws and returns null for edge cases', () => {
    expect(completionsFor({ text: '', type: null, prevBlank: true, elements: [] })).toBeNull();
    expect(completionsFor({ text: '   ', type: 'action', prevBlank: true, elements: [] })).toBeNull();
    expect(completionsFor({ text: 'She walks', type: 'action', prevBlank: true, elements: els })).toBeNull();
  });
  it('matches character names with curly apostrophes', () => {
    const name = "O" + String.fromCharCode(0x2019) + "BRIEN";
    const elWithApostrophe = parse("INT. ROOM\n\n" + name + "\nHello.");
    const typed = "O" + String.fromCharCode(0x2019) + "B";
    expect(completionsFor({ text: typed, type: 'action', prevBlank: true, elements: elWithApostrophe }))
      .toEqual({ from: 0, options: [name] });
  });
  it('matches character names with straight apostrophes', () => {
    const name = "O" + String.fromCharCode(0x27) + "BRIEN";
    const elWithStraightApostrophe = parse("INT. ROOM\n\n" + name + "\nHello.");
    const typed = "O" + String.fromCharCode(0x27) + "B";
    expect(completionsFor({ text: typed, type: 'action', prevBlank: true, elements: elWithStraightApostrophe }))
      .toEqual({ from: 0, options: [name] });
  });
});

describe('complete source (adapter)', () => {
  it('returns null for empty doc at pos 0 without throwing', () => {
    const state = EditorState.create({
      doc: '',
      extensions: [analysisField],
    });
    const ctx = new CompletionContext(state, 0, false);
    expect(() => scriptCompletionSource(ctx)).not.toThrow();
    expect(scriptCompletionSource(ctx)).toBeNull();
  });
  it('offers character names at the end of a doc', () => {
    const docWithCharacter = 'MARA\nHi.\n\nJOE\nYo.\n\nJ';
    const state = EditorState.create({
      doc: docWithCharacter,
      extensions: [analysisField],
    });
    const pos = docWithCharacter.length;
    const ctx = new CompletionContext(state, pos, false);
    const result = scriptCompletionSource(ctx);
    expect(result).not.toBeNull();
    expect(result.options.map((o) => o.label)).toContain('JOE');
  });
  it('returns null for dialogue lines', () => {
    const docWithDialogue = 'MARA\nHello there.';
    const state = EditorState.create({
      doc: docWithDialogue,
      extensions: [analysisField],
    });
    const pos = docWithDialogue.length;
    const ctx = new CompletionContext(state, pos, false);
    const result = scriptCompletionSource(ctx);
    expect(result).toBeNull();
  });
});
