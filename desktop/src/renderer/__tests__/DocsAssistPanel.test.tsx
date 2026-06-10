import { fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { DocsAssistPanel } from '../components/DocsAssistPanel';
import { useDocsAssist } from '../stores/docs-assist';
import type { EditorHandle } from '../components/RichMarkdownEditor';
import type { DocsAssistEvent } from '../../shared/api-types';

// ── helpers ─────────────────────────────────────────────────────────────────

/** Build a fake EditorHandle for tests — all methods are vi.fn() stubs. */
function makeHandle(overrides: Partial<EditorHandle> = {}) {
  const handle: EditorHandle = {
    getSelectionMarkdown: vi.fn(() => ''),
    replaceWith: vi.fn(),
    getHTML: vi.fn(() => '<p>html</p>'),
    getMarkdown: vi.fn(() => 'md'),
    ...overrides,
  };
  return { current: handle } as React.MutableRefObject<EditorHandle | null>;
}

// Capture the docs:event listener registered by the component so tests can
// fire synthetic events without an IPC backend.
type DocsEventPayload = { jotId: string; event: DocsAssistEvent };
type DocsEventListener = (payload: DocsEventPayload) => void;

/** Replace window.gb.on with a spy that captures the docs:event listener,
 *  returning a cleanup function. */
function captureDocsListener(): { fire: DocsEventListener; cleanup: () => void } {
  let captured: DocsEventListener | null = null;
  const off = vi.fn();
  window.gb = {
    ...window.gb,
    on: ((channel: string, listener: DocsEventListener) => {
      if (channel === 'docs:event') captured = listener;
      return off as () => void;
    }) as typeof window.gb.on,
  };
  return {
    fire: (payload) => captured?.(payload),
    cleanup: off,
  };
}

const JOTID = 'j-test-1';

// Reset store before each test so state never bleeds between cases.
beforeEach(() => {
  vi.clearAllMocks();
  useDocsAssist.setState({
    open: false,
    phase: 'idle',
    jotId: null,
    target: 'doc',
    mode: 'polish',
    selection: '',
    streamed: '',
    error: null,
  });
  // Restore a minimal docs stub so tests that don't override it still work.
  window.gb = {
    ...window.gb,
    docs: {
      assist: vi.fn(async () => ({ ok: true }) as const),
      assistStop: vi.fn(async () => ({ ok: true }) as const),
      exportPdf: vi.fn(async () => ({ ok: true, path: '/tmp/x.pdf' }) as const),
    },
    on: (() => () => {}) as typeof window.gb.on,
  };
});

// ── tests ────────────────────────────────────────────────────────────────────

describe('DocsAssistPanel', () => {
  it('renders quick-action buttons', () => {
    render(<DocsAssistPanel jotId={JOTID} editorHandle={makeHandle()} />);
    expect(screen.getByRole('button', { name: 'polish' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'expand' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'summarize' })).toBeInTheDocument();
  });

  it('renders a textarea and a go button', () => {
    render(<DocsAssistPanel jotId={JOTID} editorHandle={makeHandle()} />);
    expect(screen.getByPlaceholderText(/custom instruction/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /go/i })).toBeInTheDocument();
  });

  it('delta + done flow: streams text, shows proposal, accept calls replaceWith and resets', async () => {
    const { fire } = captureDocsListener();
    const handle = makeHandle();
    render(<DocsAssistPanel jotId={JOTID} editorHandle={handle} />);

    // Start a stream by clicking a quick-action button.
    fireEvent.click(screen.getByRole('button', { name: 'polish' }));

    // Verify we entered streaming phase.
    await waitFor(() => {
      expect(useDocsAssist.getState().phase).toBe('streaming');
    });

    // Fire two delta events and a done.
    act(() => {
      fire({ jotId: JOTID, event: { type: 'delta', text: 'hello ' } });
      fire({ jotId: JOTID, event: { type: 'delta', text: 'world' } });
      fire({ jotId: JOTID, event: { type: 'done', text: 'hello world' } });
    });

    // Should now be in proposal phase.
    await waitFor(() => {
      expect(useDocsAssist.getState().phase).toBe('proposal');
    });
    expect(screen.getByText(/proposal/i)).toBeInTheDocument();

    // Accept the proposal.
    fireEvent.click(screen.getByRole('button', { name: /accept/i }));

    // replaceWith must have been called with the streamed text.
    expect(handle.current?.replaceWith).toHaveBeenCalledWith(
      'hello world',
      expect.stringMatching(/^(selection|doc)$/),
    );
    // Store must have reset to idle.
    expect(useDocsAssist.getState().phase).toBe('idle');
  });

  it('error event transitions to error phase and shows retry button', async () => {
    const { fire } = captureDocsListener();
    render(<DocsAssistPanel jotId={JOTID} editorHandle={makeHandle()} />);

    fireEvent.click(screen.getByRole('button', { name: 'expand' }));

    await waitFor(() => expect(useDocsAssist.getState().phase).toBe('streaming'));

    act(() => {
      fire({ jotId: JOTID, event: { type: 'error', message: 'LLM timeout' } });
    });

    await waitFor(() => {
      expect(useDocsAssist.getState().phase).toBe('error');
    });
    expect(screen.getByText(/LLM timeout/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('user stop (error event with interrupted flag) returns to idle, not error', async () => {
    // A user-initiated stop arrives as {type:'error', interrupted:true} — the
    // panel must treat it as a deliberate action, not render a failure.
    const { fire } = captureDocsListener();
    render(<DocsAssistPanel jotId={JOTID} editorHandle={makeHandle()} />);

    fireEvent.click(screen.getByRole('button', { name: 'polish' }));
    await waitFor(() => expect(useDocsAssist.getState().phase).toBe('streaming'));

    act(() => {
      fire({ jotId: JOTID, event: { type: 'delta', text: 'partial output' } });
      fire({
        jotId: JOTID,
        event: { type: 'error', message: 'stopped', interrupted: true },
      });
    });

    await waitFor(() => {
      expect(useDocsAssist.getState().phase).toBe('idle');
    });
    expect(useDocsAssist.getState().error).toBeNull();
    // No error UI rendered for an intentional stop.
    expect(screen.queryByText('stopped')).toBeNull();
    expect(screen.queryByRole('button', { name: /retry/i })).toBeNull();
  });

  it('discard from proposal phase resets to idle', async () => {
    const { fire } = captureDocsListener();
    render(<DocsAssistPanel jotId={JOTID} editorHandle={makeHandle()} />);

    fireEvent.click(screen.getByRole('button', { name: 'polish' }));
    await waitFor(() => expect(useDocsAssist.getState().phase).toBe('streaming'));

    act(() => {
      fire({ jotId: JOTID, event: { type: 'done', text: 'proposed content' } });
    });
    await waitFor(() => expect(useDocsAssist.getState().phase).toBe('proposal'));

    fireEvent.click(screen.getByRole('button', { name: /discard/i }));
    expect(useDocsAssist.getState().phase).toBe('idle');
  });

  it('events from a different jotId are ignored', async () => {
    const { fire } = captureDocsListener();
    render(<DocsAssistPanel jotId={JOTID} editorHandle={makeHandle()} />);

    fireEvent.click(screen.getByRole('button', { name: 'polish' }));
    await waitFor(() => expect(useDocsAssist.getState().phase).toBe('streaming'));

    act(() => {
      // Event for a different jot — should be ignored.
      fire({ jotId: 'other-jot', event: { type: 'done', text: 'not ours' } });
    });

    // Still streaming.
    expect(useDocsAssist.getState().phase).toBe('streaming');
  });

  it('quick-action buttons are disabled while streaming', async () => {
    captureDocsListener();
    render(<DocsAssistPanel jotId={JOTID} editorHandle={makeHandle()} />);

    fireEvent.click(screen.getByRole('button', { name: 'polish' }));
    await waitFor(() => expect(useDocsAssist.getState().phase).toBe('streaming'));

    expect(screen.getByRole('button', { name: 'polish' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'expand' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'summarize' })).toBeDisabled();
  });

  it('stop button calls assistStop', async () => {
    captureDocsListener();
    render(<DocsAssistPanel jotId={JOTID} editorHandle={makeHandle()} />);

    fireEvent.click(screen.getByRole('button', { name: 'polish' }));
    await waitFor(() => expect(useDocsAssist.getState().phase).toBe('streaming'));

    fireEvent.click(screen.getByRole('button', { name: /stop/i }));

    await waitFor(() => {
      expect(window.gb.docs.assistStop).toHaveBeenCalledWith(JOTID);
    });
  });

  it('a pending proposal is discarded when the jotId switches (never written to the new jot)', async () => {
    // Regression: a proposal generated for jot A must not survive a switch to
    // jot B — Accept would write A's text into B's editor via the handle.
    const { fire } = captureDocsListener();
    const handle = makeHandle();
    const { rerender } = render(<DocsAssistPanel jotId={JOTID} editorHandle={handle} />);

    fireEvent.click(screen.getByRole('button', { name: 'polish' }));
    await waitFor(() => expect(useDocsAssist.getState().phase).toBe('streaming'));

    act(() => {
      fire({ jotId: JOTID, event: { type: 'done', text: "jot A's proposal" } });
    });
    await waitFor(() => expect(useDocsAssist.getState().phase).toBe('proposal'));

    // Switch to a different jot while the proposal is pending.
    rerender(<DocsAssistPanel jotId="j-other" editorHandle={handle} />);

    await waitFor(() => {
      expect(useDocsAssist.getState().phase).toBe('idle');
    });
    // No accept UI remains, and nothing was ever written into an editor.
    expect(screen.queryByRole('button', { name: /accept/i })).toBeNull();
    expect(handle.current?.replaceWith).not.toHaveBeenCalled();
    // The proposal phase needed no sidecar stop — only streams do.
    expect(window.gb.docs.assistStop).not.toHaveBeenCalled();
  });

  it('finish with empty done text accepts the accumulated delta text', async () => {
    // The sidecar may emit done without a final text payload — the proposal
    // (and accept) must then use the concatenated deltas.
    const { fire } = captureDocsListener();
    const handle = makeHandle();
    render(<DocsAssistPanel jotId={JOTID} editorHandle={handle} />);

    fireEvent.click(screen.getByRole('button', { name: 'polish' }));
    await waitFor(() => expect(useDocsAssist.getState().phase).toBe('streaming'));

    act(() => {
      fire({ jotId: JOTID, event: { type: 'delta', text: 'accumulated ' } });
      fire({ jotId: JOTID, event: { type: 'delta', text: 'deltas' } });
      fire({ jotId: JOTID, event: { type: 'done', text: '' } });
    });
    await waitFor(() => expect(useDocsAssist.getState().phase).toBe('proposal'));

    fireEvent.click(screen.getByRole('button', { name: /accept/i }));

    expect(handle.current?.replaceWith).toHaveBeenCalledWith(
      'accumulated deltas',
      expect.stringMatching(/^(selection|doc)$/),
    );
    expect(useDocsAssist.getState().phase).toBe('idle');
  });
});
