import { describe, expect, it } from 'vitest';
import { parse } from '../../fountain/parse.js';
import { LINES_PER_PAGE, paginate } from '../paginate.js';

const P = (src, opts) => paginate(parse(src), opts);
// n one-line actions occupy rows 0..2n-2 (blank line between blocks).
const actions = (n) => Array.from({ length: n }, (_, k) => `Action ${k + 1}.`).join('\n\n');
const sentences = (n, end = '.') => Array.from({ length: n }, (_, k) => `Line ${k + 1} of it${end}`).join('\n');

describe('paginate', () => {
  it('returns one empty page for an empty script', () => {
    expect(P('')).toEqual([{ number: 1, lines: [] }]);
  });

  it('positions elements with one blank line between blocks', () => {
    const [page] = P('INT. HOUSE - DAY\n\nShe waits.\n\nMARA\n(beat)\nNow.');
    expect(page.lines.map((l) => [l.type, l.y, l.x])).toEqual([
      ['scene_heading', 0, 0], ['action', 2, 0], ['character', 4, 22], ['parenthetical', 5, 16], ['dialogue', 6, 10],
    ]);
  });

  it('uppercases headings/cues/transitions and right-aligns transitions', () => {
    const [page] = P('ext. beach - day\n\nGo.\n\ncut to:\n\n');
    expect(page.lines[0].text).toBe('EXT. BEACH - DAY');
    const tr = P('Go.\n\n> fade out.')[0].lines[1];
    expect(tr).toMatchObject({ type: 'transition', text: 'FADE OUT.', x: 60 - 'FADE OUT.'.length });
  });

  it('fits exactly 27 one-line actions on a 54-line page', () => {
    const pages = P(actions(28));
    expect(pages).toHaveLength(2);
    expect(pages[0].lines).toHaveLength(27);
    expect(pages[0].lines.at(-1).y).toBe(52);
    expect(pages[1].lines[0]).toMatchObject({ y: 0, text: 'Action 28.' });
  });

  it('never leaves a scene heading at the bottom of a page', () => {
    const pages = P(`${actions(26)}\n\nINT. CAVE - NIGHT\n\nDark.`);
    expect(pages[0].lines.at(-1).type).toBe('action');
    expect(pages[1].lines[0]).toMatchObject({ type: 'scene_heading', y: 0 });
  });

  it('splits long dialogue with (MORE) and CONT\'D, ≥2 lines each side', () => {
    const pages = P(`${actions(20)}\n\nMARA\n${sentences(20)}`);
    const p1 = pages[0].lines;
    expect(p1.at(-1)).toMatchObject({ type: 'more', text: '(MORE)', y: 53, x: 22 });
    expect(p1.filter((l) => l.type === 'dialogue')).toHaveLength(12);
    expect(pages[1].lines[0]).toMatchObject({ type: 'character', text: "MARA (CONT'D)", y: 0 });
    expect(pages[1].lines.filter((l) => l.type === 'dialogue')).toHaveLength(8);
  });

  it('prefers a sentence boundary when splitting dialogue', () => {
    const lines = Array.from({ length: 20 }, (_, k) => (k === 9 ? 'Stop here.' : 'and on'));
    const pages = P(`${actions(20)}\n\nMARA\n${lines.join('\n')}`);
    expect(pages[0].lines.filter((l) => l.type === 'dialogue').at(-1).text).toBe('Stop here.');
  });

  it('moves a short dialogue block whole instead of splitting it', () => {
    const pages = P(`${actions(26)}\n\nMARA\nOne.\nTwo.\nThree.`);
    expect(pages[0].lines.some((l) => l.type === 'character')).toBe(false);
    expect(pages[1].lines[0]).toMatchObject({ type: 'character', text: 'MARA' });
  });

  it('splits action at a sentence end, otherwise moves it whole', () => {
    const split = P(`${actions(20)}\n\n${sentences(20)}`);
    expect(split[0].lines.at(-1)).toMatchObject({ y: 53, text: 'Line 14 of it.' });
    expect(split[1].lines[0]).toMatchObject({ y: 0, text: 'Line 15 of it.' });

    const moved = P(`${actions(20)}\n\n${sentences(20, '')}`);
    expect(moved[0].lines.at(-1).text).toBe('Action 20.');
    expect(moved[1].lines[0].text).toBe('Line 1 of it');
  });

  it('honours forced page breaks', () => {
    const pages = P('One.\n\n===\n\nTwo.');
    expect(pages.map((p) => p.lines.map((l) => l.text))).toEqual([['One.'], ['Two.']]);
  });

  it('numbers scenes when asked, keeping explicit numbers', () => {
    const [page] = P('INT. A - DAY\n\nx\n\nINT. B - DAY #7B#\n\ny\n\nINT. C - DAY', { sceneNumbers: true });
    expect(page.lines.filter((l) => l.sceneNumber).map((l) => l.sceneNumber)).toEqual(['1', '7B', '3']);
    expect(P('INT. A - DAY')[0].lines[0].sceneNumber).toBeUndefined();
  });

  it('lays dual dialogue side by side', () => {
    const [page] = P('BRICK\nScrew it.\n\nSTEEL ^\nScrew it.');
    const cues = page.lines.filter((l) => l.type === 'character');
    expect(cues.map((c) => c.y)).toEqual([0, 0]);
    expect(cues[1].x).toBeGreaterThan(cues[0].x + 20);
  });

  it('strips notes and boneyard from printed text', () => {
    const [page] = P('She waits [[fix]] here.');
    expect(page.lines[0].text).toBe('She waits here.');
  });

  it('never loses, duplicates or overflows lines on oversized blocks', () => {
    const src = `INT. A - DAY\n\n${sentences(150, '')}\n\nMARA\n${sentences(120)}\n\n${actions(40)}`;
    const pages = P(src);
    for (const p of pages) {
      for (const l of p.lines) expect(l.y).toBeLessThan(LINES_PER_PAGE);
      expect(p.lines.at(-1)?.type).not.toBe('scene_heading');
    }
    const texts = pages.flatMap((p) => p.lines).filter((l) => l.type !== 'more' && l.el !== -1).map((l) => l.text);
    expect(texts.filter((t) => /^Line \d+ of it$/.test(t))).toHaveLength(150);
    expect(texts.filter((t) => /^Line \d+ of it\.$/.test(t))).toHaveLength(120);
    expect(texts.filter((t) => /^Action \d+\.$/.test(t))).toHaveLength(40);
  });

  it('repeats dialogue splits with (MORE)/(CONT\'D) for oversized blocks', () => {
    const pages = P(`${actions(1)}\n\nMARA\n${sentences(120)}`);
    // Every page except the last must end with (MORE)
    for (let p = 0; p < pages.length - 1; p++) {
      expect(pages[p].lines.at(-1)).toMatchObject({ type: 'more', text: '(MORE)' });
    }
    // Every page after the first must start with MARA (CONT'D)
    for (let p = 1; p < pages.length; p++) {
      expect(pages[p].lines[0]).toMatchObject({ type: 'character', text: "MARA (CONT'D)" });
    }
    // All 120 dialogue lines must be present exactly once
    const dialogueLines = pages.flatMap((p) => p.lines).filter((l) => l.type === 'dialogue' && l.el !== -1);
    expect(dialogueLines).toHaveLength(120);
  });

  it('falls back to sequential blocks for dual dialogue exceeding page height', () => {
    const pages = P(`BRICK\n${sentences(70)}\n\nSTEEL ^\n${sentences(70)}`);
    // All lines must have y < 54
    for (const p of pages) {
      for (const l of p.lines) expect(l.y).toBeLessThan(LINES_PER_PAGE);
    }
    // All lines of both speakers must be present
    const allLines = pages.flatMap((p) => p.lines).filter((l) => l.el !== -1 && l.type !== 'more');
    expect(allLines.filter((l) => l.type === 'character')).toHaveLength(2); // BRICK and STEEL cues (may include CONT'D variants)
    expect(allLines.filter((l) => l.type === 'dialogue')).toHaveLength(140); // 70 + 70 dialogue lines
  });

  it('recognizes curly quotes as sentence ends when splitting dialogue', () => {
    const lines = Array.from({ length: 20 }, (_, k) => (k === 9 ? 'Stop here.”' : 'and on'));
    const pages = P(`${actions(20)}\n\nMARA\n${lines.join('\n')}`);
    expect(pages[0].lines.filter((l) => l.type === 'dialogue').at(-1).text).toBe('Stop here.”');
  });

  it('recognizes straight quotes as sentence ends when splitting dialogue', () => {
    const lines = Array.from({ length: 20 }, (_, k) => (k === 9 ? 'Stop here."' : 'and on'));
    const pages = P(`${actions(20)}\n\nMARA\n${lines.join('\n')}`);
    expect(pages[0].lines.filter((l) => l.type === 'dialogue').at(-1).text).toBe('Stop here."');
  });
});
