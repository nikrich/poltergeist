import { setFocusMode } from '../lib/focus-mode';
import { isMac } from '../lib/platform';
import { Lucide } from './Lucide';

/** Replaces the top bar / note header while focus mode is on: a thin
 * window-drag strip (left padding clears the macOS traffic lights) with one
 * way out for mouse users. */
export function FocusBar() {
  return (
    <div
      data-testid="focus-bar"
      className="flex h-9 flex-shrink-0 items-center justify-end pr-3"
      style={{ WebkitAppRegion: 'drag', paddingLeft: isMac ? 80 : 12 }}
    >
      <button
        type="button"
        aria-label="exit focus mode"
        onClick={() => void setFocusMode(false)}
        className="flex items-center gap-[6px] rounded-sm px-2 py-[3px] font-mono text-10 text-ink-3 opacity-60 hover:bg-vellum hover:text-ink-1 hover:opacity-100"
        style={{ WebkitAppRegion: 'no-drag' }}
      >
        <Lucide name="minimize-2" size={12} /> exit focus · esc
      </button>
    </div>
  );
}
