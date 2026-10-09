import { useEffect, useMemo, useState } from 'react';

export const WAVEFORM_BARS = 48;
/** Percent height of a silent bar, so the baseline stays visible. */
const MIN_BAR = 6;
const RESUBSCRIBE_DELAY_MS = 1000;

/** The last WAVEFORM_BARS audio levels (0..1, 100 ms each) of the recording
 *  in progress, oldest first; zeros until the first levels arrive. */
export function useRecorderLevels(active: boolean): number[] {
  const [levels, setLevels] = useState<number[]>(() => Array(WAVEFORM_BARS).fill(0));

  useEffect(() => {
    if (!active) return;
    const off = window.gb.on('recorder:levels:event', (event) => {
      if (event.type !== 'levels' || event.levels.length === 0) return;
      setLevels((prev) => [...prev, ...event.levels].slice(-WAVEFORM_BARS));
    });
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    // The stream ends when the WAV stops growing; while this view is still up
    // (e.g. it opened a moment before capture wrote its first bytes), follow again.
    const subscribe = () => {
      void window.gb.recorder.levelsSubscribe().then(() => {
        if (!cancelled) timer = setTimeout(subscribe, RESUBSCRIBE_DELAY_MS);
      });
    };
    subscribe();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      off();
      void window.gb.recorder.levelsUnsubscribe();
    };
  }, [active]);

  return levels;
}

interface Props {
  /** Follow the recording's real audio levels; otherwise a static decoration. */
  live?: boolean;
}

export function Waveform({ live = false }: Props) {
  const levels = useRecorderLevels(live);
  const decorative = useMemo(
    () => Array.from({ length: WAVEFORM_BARS }, () => 0.2 + Math.random() * 0.8),
    [],
  );
  const heights = live ? levels : decorative;

  return (
    <div
      data-testid="waveform"
      aria-hidden="true"
      className="flex h-9 items-center gap-[2px] rounded-r6 border border-hairline bg-paper px-3"
    >
      {heights.map((h, i) => (
        <div
          key={i}
          className={`flex-1 rounded-[1px] ${live ? 'bg-neon' : 'bg-ink-3'}`}
          style={{
            height: `${Math.max(MIN_BAR, h * 100)}%`,
            opacity: live ? 0.45 + h * 0.55 : 0.4 + h * 0.4,
            transition: live ? 'height 90ms linear' : undefined,
          }}
        />
      ))}
    </div>
  );
}
