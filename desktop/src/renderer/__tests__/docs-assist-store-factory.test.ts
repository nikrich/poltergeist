import { describe, expect, it } from 'vitest';
import { createDocsAssistStore, useDocsAssist } from '../stores/docs-assist';

describe('createDocsAssistStore', () => {
  it('makes independent stores; the panel keeps its own', () => {
    const a = createDocsAssistStore();
    const b = createDocsAssistStore();
    a.getState().start({ jotId: 'inline-1', mode: 'continue', target: 'doc', selection: '' });
    a.getState().appendDelta('hi');
    a.getState().finish('');
    expect(a.getState().phase).toBe('proposal');
    expect(a.getState().streamed).toBe('hi');
    expect(b.getState().phase).toBe('idle');
    expect(useDocsAssist.getState().phase).toBe('idle');
  });
});
