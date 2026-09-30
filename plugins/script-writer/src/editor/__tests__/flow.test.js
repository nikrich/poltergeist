import { describe, expect, it } from 'vitest';
import { applyType, looksLikeCue, markerRanges, nextInCycle, stripMarkers } from '../flow.js';

describe('flow', () => {
  it('strips forcing markers and parens', () => {
    expect(stripMarkers('@McCLANE')).toBe('McCLANE');
    expect(stripMarkers('>THE END<')).toBe('THE END');
    expect(stripMarkers('(quietly)')).toBe('quietly');
    expect(stripMarkers('.FLASHBACK')).toBe('FLASHBACK');
  });

  it('rewrites a line for each element type', () => {
    expect(applyType('mara', 'character')).toBe('MARA');
    expect(applyType('quietly', 'parenthetical')).toBe('(quietly)');
    expect(applyType('cut to:', 'transition')).toBe('CUT TO:');
    expect(applyType('fade out.', 'transition')).toBe('>FADE OUT.');
    expect(applyType('int. house - day', 'scene_heading')).toBe('INT. HOUSE - DAY');
    expect(applyType('flashback', 'scene_heading')).toBe('.FLASHBACK');
    expect(applyType('MARA', 'action')).toBe('!MARA');
    expect(applyType('(beat)', 'action')).toBe('beat');
    expect(applyType('the end', 'centered')).toBe('>the end<');
  });

  it('cycles types, only offering parenthetical inside dialogue', () => {
    expect(nextInCycle('action', 1, false)).toBe('character');
    expect(nextInCycle('character', 1, false)).toBe('transition');
    expect(nextInCycle('character', 1, true)).toBe('parenthetical');
    expect(nextInCycle('scene_heading', 1, false)).toBe('action');
    expect(nextInCycle('action', -1, false)).toBe('scene_heading');
    expect(nextInCycle('dialogue', 1, true)).toBe('parenthetical');
    expect(nextInCycle(null, 1, false)).toBe('character');
  });

  it('detects cue-looking lines', () => {
    expect(looksLikeCue('MARA')).toBe(true);
    expect(looksLikeCue('INT. HOUSE')).toBe(false);
    expect(looksLikeCue('CUT TO:')).toBe(false);
    expect(looksLikeCue('Mara')).toBe(false);
  });

  it('finds marker ranges to dim', () => {
    expect(markerRanges('.FLASHBACK', 'scene_heading')).toEqual([[0, 1, 'sw-marker']]);
    expect(markerRanges('INT. A #4#', 'scene_heading')).toEqual([[7, 10, 'sw-marker']]);
    expect(markerRanges('>END<', 'centered')).toEqual([[0, 1, 'sw-marker'], [4, 5, 'sw-marker']]);
    expect(markerRanges('STEEL ^', 'character')).toEqual([[6, 7, 'sw-marker']]);
    expect(markerRanges('Go [[fix]] now', 'action')).toEqual([[3, 10, 'sw-note']]);
  });
});
