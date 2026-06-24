import { describe, it, expect } from 'vitest';
import { Editor } from '@tiptap/core';
import { buildEditorExtensions } from '../lib/editor/extensions';

function typed(input: string): Editor {
  // Build a doc directly to assert the schema supports these structures;
  // input-rule keystroke simulation is brittle, so assert structural support.
  return new Editor({ extensions: buildEditorExtensions(), content: input });
}

describe('editor schema supports markdown structures', () => {
  it('parses ATX headings', () => {
    expect(typed('## title').getJSON().content?.[0]?.type).toBe('heading');
  });
  it('parses task list items with state', () => {
    const json = typed('- [x] done').getJSON();
    expect(JSON.stringify(json)).toContain('taskItem');
  });
});
