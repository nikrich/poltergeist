import { describe, expect, it } from 'vitest';
import { renderNoteBlocks, trimToBudget } from '../budget.js';

const note = (path, modified, len) => ({ path, modified, text: 'x'.repeat(len) });

describe('trimToBudget', () => {
  it('keeps everything under budget', () => {
    const { kept, dropped } = trimToBudget([note('a.md', '2026-07-01', 10), note('b.md', '2026-07-02', 10)], 100);
    expect(kept.map((n) => n.path)).toEqual(['a.md', 'b.md']);
    expect(dropped).toEqual([]);
  });
  it('drops oldest whole notes first', () => {
    const { kept, dropped } = trimToBudget(
      [note('new.md', '2026-07-07', 60), note('old.md', '2026-07-01', 60), note('mid.md', '2026-07-04', 60)],
      130,
    );
    expect(dropped).toEqual(['old.md']);
    expect(kept.map((n) => n.path)).toEqual(['mid.md', 'new.md']);
  });
  it('always keeps at least one note', () => {
    const { kept } = trimToBudget([note('huge.md', '2026-07-01', 500)], 10);
    expect(kept.length).toBe(1);
  });
});

describe('renderNoteBlocks', () => {
  it('wraps notes in path-tagged blocks', () => {
    const out = renderNoteBlocks([{ path: 'a.md', modified: '2026-07-01', text: 'hello' }]);
    expect(out).toBe('<note path="a.md" modified="2026-07-01">\nhello\n</note>');
  });
});
