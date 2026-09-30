import { describe, expect, it } from 'vitest';
import { parse } from '../parse.js';
import { characters, cueName, joinBlocks, moveScene, sceneBlocks, sceneInsertPos, sceneRange, scenes } from '../outline.js';

const SRC = 'FADE IN:\n\nINT. A - DAY\n\n= Mara arrives.\n\nMARA\nHi.\n\nINT. B - NIGHT #9#\n\nJOE (V.O.)\nYo.\n\nMARA (CONT\'D)\nAgain.\n\nEXT. C - DAY\n\nEnd.\n';

describe('outline', () => {
  it('lists scenes with numbers and first synopsis', () => {
    expect(scenes(parse(SRC))).toEqual([
      { index: 0, number: '1', heading: 'INT. A - DAY', line: 2, synopsis: 'Mara arrives.' },
      { index: 1, number: '9', heading: 'INT. B - NIGHT', line: 9, synopsis: '' },
      { index: 2, number: '3', heading: 'EXT. C - DAY', line: 17, synopsis: '' },
    ]);
  });

  it('normalises cue names', () => {
    expect(cueName("mara (cont'd) ^")).toBe('MARA');
  });

  it('counts speeches per character, most first', () => {
    expect(characters(parse(SRC))).toEqual([
      { name: 'MARA', count: 2, lines: [6, 14] },
      { name: 'JOE', count: 1, lines: [11] },
    ]);
  });

  it('moves a scene block, keeping the preamble and one blank line between scenes', () => {
    const out = moveScene(SRC, 2, 0);
    expect(scenes(parse(out)).map((s) => s.heading)).toEqual(['EXT. C - DAY', 'INT. A - DAY', 'INT. B - NIGHT']);
    expect(out.startsWith('FADE IN:\n\nEXT. C - DAY\n\nEnd.\n\nINT. A - DAY')).toBe(true);
    expect(out.endsWith('Again.\n')).toBe(true);
  });

  it('is a no-op for out-of-range or same-index moves', () => {
    expect(moveScene(SRC, 1, 1)).toBe(SRC);
    expect(moveScene(SRC, 5, 0)).toBe(SRC);
  });
});

describe('scene blocks', () => {
  const T = 'FADE IN:\n\nINT. A - DAY\n\nHi.\n\n\nINT. B - DAY\n\nYo.\n';
  it('splits preamble and scenes, trimming trailing blank lines', () => {
    expect(sceneBlocks(T)).toEqual({ pre: 'FADE IN:', blocks: [{ line: 2, text: 'INT. A - DAY\n\nHi.' }, { line: 7, text: 'INT. B - DAY\n\nYo.' }], trailingNewline: true });
  });
  it('joins with one blank line and round-trips normalised text', () => {
    expect(joinBlocks(sceneBlocks(T))).toBe('FADE IN:\n\nINT. A - DAY\n\nHi.\n\nINT. B - DAY\n\nYo.\n');
    const norm = joinBlocks(sceneBlocks(T));
    expect(joinBlocks(sceneBlocks(norm))).toBe(norm);
  });
  it('handles no headings and no preamble', () => {
    expect(sceneBlocks('Just action.')).toEqual({ pre: 'Just action.', blocks: [], trailingNewline: false });
    expect(joinBlocks(sceneBlocks('INT. A - DAY\n\nGo.'))).toBe('INT. A - DAY\n\nGo.');
  });
  it('finds the scene range around a line and the insert position after it', () => {
    expect(sceneRange(T, 4)).toEqual({ startLine: 2, endLine: 4 });
    expect(sceneRange(T, 0)).toEqual({ startLine: 0, endLine: 0 });
    expect(sceneRange(T, 9)).toEqual({ startLine: 7, endLine: 9 });
    expect(sceneInsertPos(T, 4)).toBe('FADE IN:\n\nINT. A - DAY\n\nHi.'.length);
  });
});
