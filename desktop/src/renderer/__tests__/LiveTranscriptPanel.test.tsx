import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { LiveTranscriptPanel } from '../components/LiveTranscriptPanel';
import { useLiveTranscript, useLiveTranscriptStream } from '../stores/live-transcript';
import type { LiveTranscriptEvent } from '../../shared/api-types';

const seg = (seq: number, text: string, lang = 'en', t0 = seq * 5): LiveTranscriptEvent => ({
  type: 'segment',
  seq,
  t0,
  t1: t0 + 4,
  text,
  lang,
});

const apply = (e: LiveTranscriptEvent) => act(() => useLiveTranscript.getState().apply(e));

beforeEach(() => {
  useLiveTranscript.getState().reset();
});

describe('live transcript store', () => {
  it('appends segments in order and drops replayed duplicates', () => {
    const { apply: a } = useLiveTranscript.getState();
    a(seg(1, 'one'));
    a(seg(2, 'two'));
    a(seg(1, 'one')); // replay after a re-subscribe
    expect(useLiveTranscript.getState().segments.map((s) => s.text)).toEqual(['one', 'two']);
  });

  it('tracks status and end', () => {
    const { apply: a } = useLiveTranscript.getState();
    a({ type: 'status', state: 'unavailable', reason: 'no model', lag_s: 0 });
    a({ type: 'end' });
    const s = useLiveTranscript.getState();
    expect(s.state).toBe('unavailable');
    expect(s.reason).toBe('no model');
    expect(s.ended).toBe(true);
  });
});

describe('LiveTranscriptPanel', () => {
  it('shows a listening hint before the first words', () => {
    apply({ type: 'status', state: 'live', reason: null, lag_s: 0 });
    render(<LiveTranscriptPanel />);
    expect(screen.getByText(/listening/i)).toBeInTheDocument();
  });

  it('renders segments with a timestamp and language badge', () => {
    apply(seg(1, 'Goeie môre almal', 'af', 65));
    apply(seg(2, 'Let us start', 'en', 70));
    render(<LiveTranscriptPanel />);
    expect(screen.getByText('Goeie môre almal')).toBeInTheDocument();
    expect(screen.getByText('01:05')).toBeInTheDocument();
    expect(screen.getByText('af')).toBeInTheDocument();
    expect(screen.getByText('en')).toBeInTheDocument();
  });

  it('explains when live transcription is unavailable', () => {
    apply({ type: 'status', state: 'unavailable', reason: 'whisper-server failed twice', lag_s: 0 });
    render(<LiveTranscriptPanel />);
    expect(screen.getByText(/whisper-server failed twice/)).toBeInTheDocument();
    expect(screen.getByText(/recording continues/i)).toBeInTheDocument();
  });

  it('says live is off when the stream ends without a session', () => {
    apply({ type: 'end' });
    render(<LiveTranscriptPanel />);
    expect(screen.getByText(/live transcript is off/i)).toBeInTheDocument();
  });

  it('shows the lag only when well behind', () => {
    apply({ type: 'status', state: 'live', reason: null, lag_s: 4 });
    const { rerender } = render(<LiveTranscriptPanel />);
    expect(screen.queryByText(/behind/)).not.toBeInTheDocument();
    apply({ type: 'status', state: 'live', reason: null, lag_s: 21 });
    rerender(<LiveTranscriptPanel />);
    expect(screen.getByText(/~21s behind/)).toBeInTheDocument();
  });

  it('pauses auto-scroll when you scroll up and offers jump to live', () => {
    apply(seg(1, 'one'));
    render(<LiveTranscriptPanel />);
    const list = screen.getByRole('log');
    Object.defineProperty(list, 'scrollHeight', { configurable: true, value: 1000 });
    Object.defineProperty(list, 'clientHeight', { configurable: true, value: 300 });
    list.scrollTop = 100; // well above the bottom
    fireEvent.scroll(list);
    apply(seg(2, 'two'));
    const jump = screen.getByRole('button', { name: /jump to live/i });
    expect(list.scrollTop).toBe(100); // did not yank the reader down
    fireEvent.click(jump);
    expect(list.scrollTop).toBe(1000);
    expect(screen.queryByRole('button', { name: /jump to live/i })).not.toBeInTheDocument();
  });

  it('shows finalising once the recording stops', () => {
    apply(seg(1, 'one'));
    apply({ type: 'status', state: 'finalizing', reason: null, lag_s: 0 });
    render(<LiveTranscriptPanel />);
    expect(screen.getByText(/finalising transcript/i)).toBeInTheDocument();
  });
});

describe('useLiveTranscriptStream', () => {
  it('subscribes while active, feeds events into the store, unsubscribes after', async () => {
    let listener: ((e: LiveTranscriptEvent) => void) | null = null;
    const on = vi.spyOn(window.gb, 'on').mockImplementation(((_ch: string, l: never) => {
      listener = l;
      return () => {
        listener = null;
      };
    }) as never);
    const sub = vi.spyOn(window.gb.recorder, 'liveSubscribe');
    const unsub = vi.spyOn(window.gb.recorder, 'liveUnsubscribe');

    function Harness({ active }: { active: boolean }) {
      useLiveTranscriptStream(active);
      return null;
    }
    const { rerender } = render(<Harness active />);
    expect(sub).toHaveBeenCalledOnce();
    act(() => listener?.(seg(1, 'hello')));
    expect(useLiveTranscript.getState().segments).toHaveLength(1);

    rerender(<Harness active={false} />);
    expect(unsub).toHaveBeenCalled();
    expect(listener).toBeNull();
    on.mockRestore();
  });
});
