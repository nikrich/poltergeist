import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Waveform, WAVEFORM_BARS } from '../components/Waveform';
import type { RecorderLevelsEvent } from '../../shared/api-types';

function bars(): number[] {
  return Array.from(screen.getByTestId('waveform').children).map((el) =>
    parseFloat((el as HTMLElement).style.height),
  );
}

describe('Waveform', () => {
  it('decorative mode renders static bars and never subscribes', () => {
    const sub = vi.spyOn(window.gb.recorder, 'levelsSubscribe');
    render(<Waveform />);
    expect(bars()).toHaveLength(WAVEFORM_BARS);
    expect(sub).not.toHaveBeenCalled();
  });

  it('live mode starts flat and scrolls real levels in from the right', () => {
    let listener: ((e: RecorderLevelsEvent) => void) | null = null;
    const on = vi.spyOn(window.gb, 'on').mockImplementation(((_ch: string, l: never) => {
      listener = l;
      return () => {
        listener = null;
      };
    }) as never);
    const sub = vi.spyOn(window.gb.recorder, 'levelsSubscribe');
    const unsub = vi.spyOn(window.gb.recorder, 'levelsUnsubscribe');

    const { unmount } = render(<Waveform live />);
    expect(sub).toHaveBeenCalledOnce();
    expect(Math.max(...bars())).toBeLessThan(10); // silence = flat (min height)

    act(() => listener?.({ type: 'levels', levels: [1, 0.5] }));
    const h = bars();
    expect(h).toHaveLength(WAVEFORM_BARS);
    expect(h[WAVEFORM_BARS - 1]).toBeCloseTo(50, 0); // newest on the right
    expect(h[WAVEFORM_BARS - 2]).toBeCloseTo(100, 0);

    // More than a window's worth keeps only the latest bars.
    act(() => listener?.({ type: 'levels', levels: Array(WAVEFORM_BARS + 5).fill(0) }));
    expect(Math.max(...bars())).toBeLessThan(10);

    unmount();
    expect(unsub).toHaveBeenCalled();
    expect(listener).toBeNull();
    on.mockRestore();
  });
});
