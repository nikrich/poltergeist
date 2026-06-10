import { beforeEach, describe, expect, it } from 'vitest';
import { useDocsAssist } from '../stores/docs-assist';

// Mirror the reset pattern from chat-store.test.ts — reset to a known idle
// baseline before each test so store state never leaks between cases.
const idle = {
  open: false,
  phase: 'idle' as const,
  jotId: null,
  target: 'doc' as const,
  mode: 'polish' as const,
  selection: '',
  streamed: '',
  error: null,
};

beforeEach(() => {
  useDocsAssist.setState(idle);
});

describe('docs-assist store', () => {
  it('starts in idle phase with empty fields', () => {
    const s = useDocsAssist.getState();
    expect(s.phase).toBe('idle');
    expect(s.streamed).toBe('');
    expect(s.error).toBeNull();
  });

  it('start transitions to streaming and records request params', () => {
    useDocsAssist.getState().start({
      jotId: 'j1',
      mode: 'expand',
      target: 'selection',
      selection: 'some selected text',
    });
    const s = useDocsAssist.getState();
    expect(s.phase).toBe('streaming');
    expect(s.jotId).toBe('j1');
    expect(s.mode).toBe('expand');
    expect(s.target).toBe('selection');
    expect(s.selection).toBe('some selected text');
    expect(s.streamed).toBe('');
    expect(s.error).toBeNull();
  });

  it('appendDelta accumulates streamed text', () => {
    useDocsAssist.getState().start({ jotId: 'j1', mode: 'polish', target: 'doc', selection: '' });
    useDocsAssist.getState().appendDelta('hel');
    useDocsAssist.getState().appendDelta('lo');
    expect(useDocsAssist.getState().streamed).toBe('hello');
  });

  it('finish with non-empty text transitions to proposal and sets streamed', () => {
    useDocsAssist.getState().start({ jotId: 'j1', mode: 'polish', target: 'doc', selection: '' });
    useDocsAssist.getState().appendDelta('partial');
    useDocsAssist.getState().finish('full final text');
    const s = useDocsAssist.getState();
    expect(s.phase).toBe('proposal');
    expect(s.streamed).toBe('full final text');
  });

  it('finish with empty string keeps accumulated deltas', () => {
    useDocsAssist.getState().start({ jotId: 'j1', mode: 'polish', target: 'doc', selection: '' });
    useDocsAssist.getState().appendDelta('delta text');
    // done event arrived with no text payload — accumulated deltas are kept
    useDocsAssist.getState().finish('');
    const s = useDocsAssist.getState();
    expect(s.phase).toBe('proposal');
    expect(s.streamed).toBe('delta text');
  });

  it('fail during streaming transitions to error', () => {
    useDocsAssist.getState().start({ jotId: 'j1', mode: 'polish', target: 'doc', selection: '' });
    useDocsAssist.getState().appendDelta('partial');
    useDocsAssist.getState().fail('LLM timeout');
    const s = useDocsAssist.getState();
    expect(s.phase).toBe('error');
    expect(s.error).toBe('LLM timeout');
  });

  it('reset from streaming clears phase, streamed, error, and selection', () => {
    useDocsAssist.getState().start({
      jotId: 'j1',
      mode: 'expand',
      target: 'selection',
      selection: 'my selection',
    });
    useDocsAssist.getState().appendDelta('some text');
    useDocsAssist.getState().reset();
    const s = useDocsAssist.getState();
    expect(s.phase).toBe('idle');
    expect(s.streamed).toBe('');
    expect(s.error).toBeNull();
    expect(s.selection).toBe('');
  });

  it('reset from proposal clears phase and streamed', () => {
    useDocsAssist.getState().start({ jotId: 'j1', mode: 'polish', target: 'doc', selection: '' });
    useDocsAssist.getState().finish('proposed text');
    useDocsAssist.getState().reset();
    expect(useDocsAssist.getState().phase).toBe('idle');
    expect(useDocsAssist.getState().streamed).toBe('');
  });

  it('reset from error clears error', () => {
    useDocsAssist.getState().start({ jotId: 'j1', mode: 'polish', target: 'doc', selection: '' });
    useDocsAssist.getState().fail('boom');
    useDocsAssist.getState().reset();
    expect(useDocsAssist.getState().phase).toBe('idle');
    expect(useDocsAssist.getState().error).toBeNull();
  });

  it('toggleOpen flips the open flag', () => {
    expect(useDocsAssist.getState().open).toBe(false);
    useDocsAssist.getState().toggleOpen();
    expect(useDocsAssist.getState().open).toBe(true);
    useDocsAssist.getState().toggleOpen();
    expect(useDocsAssist.getState().open).toBe(false);
  });
});
