import { describe, expect, it } from 'vitest';
import {
  cursorContext,
  extractPrompts,
  frontmatterRange,
  inQueryFence,
} from '../lib/template-editor/analyze';
import { TEMPLATE } from './helpers/template-registry';

/** `text` with the cursor at the `‸` marker removed. */
function at(marked: string): [string, number] {
  const pos = marked.indexOf('‸');
  return [marked.replace('‸', ''), pos];
}

describe('template text analysis', () => {
  it('finds the frontmatter block', () => {
    const fm = frontmatterRange(TEMPLATE)!;
    expect(TEMPLATE.slice(fm.innerEnd, fm.bodyStart)).toBe('---\n');
    expect(TEMPLATE.slice(fm.bodyStart).startsWith('# 1-1 with')).toBe(true);
    expect(frontmatterRange('# no frontmatter\n')).toBeNull();
    expect(frontmatterRange('---\nnever closed\n')).toBeNull();
  });

  it('extracts prompts in block style, type before or after id, ignoring frontmatter ids', () => {
    expect(extractPrompts(TEMPLATE)).toEqual([
      { id: 'person', type: 'person' },
      { id: 'focus', type: 'text' },
    ]);
  });

  it('extracts prompts in flow style and defaults the type to text', () => {
    const src = '---\ntemplate:\n  name: x\n  prompts: [{id: who, type: person}, {id: note}]\n---\n';
    expect(extractPrompts(src)).toEqual([
      { id: 'who', type: 'person' },
      { id: 'note', type: 'text' },
    ]);
  });

  it('keeps a block item whole when a string in it holds a placeholder', () => {
    const src = '---\ntemplate:\n  prompts:\n    - type: person\n      ask: "With {{context}}?"\n      id: who\n---\n';
    expect(extractPrompts(src)).toEqual([{ id: 'who', type: 'person' }]);
  });

  it('reports a prompt type the editor does not know as-is', () => {
    const src = '---\ntemplate:\n  prompts:\n    - id: mood\n      type: rating\n---\n';
    expect(extractPrompts(src)).toEqual([{ id: 'mood', type: 'rating' }]);
  });

  it('knows when a position is inside a query fence', () => {
    const typePos = TEMPLATE.indexOf('type: action_item');
    expect(inQueryFence(TEMPLATE, typePos)).toBe(true);
    expect(inQueryFence(TEMPLATE, TEMPLATE.indexOf('```query'))).toBe(false);
    expect(inQueryFence(TEMPLATE, TEMPLATE.indexOf('# 1-1'))).toBe(false);
    expect(inQueryFence(TEMPLATE, TEMPLATE.lastIndexOf('```'))).toBe(false);
    expect(inQueryFence('```text\ntype: x\n```\n', 9)).toBe(false);
  });

  it('classifies placeholder positions', () => {
    expect(cursorContext(...at('# {{‸'))).toEqual({ kind: 'variable', from: 4, prefix: '' });
    expect(cursorContext(...at('# {{ per‸'))).toEqual({ kind: 'variable', from: 5, prefix: 'per' });
    expect(cursorContext(...at('{{person.li‸'))).toEqual({
      kind: 'field',
      from: 9,
      prefix: 'li',
      ownerPath: ['person'],
    });
    expect(cursorContext(...at('{{now.date.‸'))).toMatchObject({ kind: 'field', ownerPath: ['now', 'date'] });
    expect(cursorContext(...at('{{date | fo‸'))).toEqual({ kind: 'filter', from: 9, prefix: 'fo' });
    expect(cursorContext(...at('{{date | format: D‸'))).toBeNull();
    expect(cursorContext(...at('{{x}} ‸'))).toBeNull();
    expect(cursorContext(...at('{{ a + ‸'))).toBeNull();
  });

  it('offers prompt types only on a type line inside prompts', () => {
    const src = TEMPLATE.replace('      type: person', '      type: pe‸');
    expect(cursorContext(...at(src))).toMatchObject({ kind: 'prompt-type', prefix: 'pe' });
    const fmType = TEMPLATE.replace('    type: meeting', '    type: me‸');
    expect(cursorContext(...at(fmType))).toBeNull();
  });

  it('classifies query keys and values', () => {
    const key = TEMPLATE.replace('status: open', 'sta‸');
    expect(cursorContext(...at(key))).toMatchObject({ kind: 'query-key', prefix: 'sta' });
    const value = TEMPLATE.replace('status: open', 'status: op‸');
    expect(cursorContext(...at(value))).toMatchObject({ kind: 'query-value', key: 'status', prefix: 'op' });
    const quoted = TEMPLATE.replace('status: open', 'Type: "acti‸');
    expect(cursorContext(...at(quoted))).toMatchObject({ kind: 'query-value', key: 'type', prefix: 'acti' });
    const inQueryPlaceholder = TEMPLATE.replace('status: open', 'mentions: "{{person.‸');
    expect(cursorContext(...at(inQueryPlaceholder))).toMatchObject({ kind: 'field' });
  });
});
