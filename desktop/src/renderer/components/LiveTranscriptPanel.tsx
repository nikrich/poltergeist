import { useLayoutEffect, useRef, useState } from 'react';
import { Eyebrow } from './Eyebrow';
import { Lucide } from './Lucide';
import { Pill } from './Pill';
import { mmss } from '../lib/format';
import { useLiveTranscript } from '../stores/live-transcript';

/** Only worth mentioning once the text trails speech noticeably. */
const LAG_NOTICE_S = 15;
/** Within this many px of the bottom counts as "following along". */
const BOTTOM_SLACK_PX = 24;

/** The transcript as it is being spoken, fed by useLiveTranscriptStream. */
export function LiveTranscriptPanel() {
  const { segments, state, reason, lagS, ended } = useLiveTranscript();
  const listRef = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);

  // Keep the newest line in view unless the reader scrolled up to reread.
  useLayoutEffect(() => {
    const el = listRef.current;
    if (el && following) el.scrollTop = el.scrollHeight;
  }, [segments.length, following]);

  const onScroll = () => {
    const el = listRef.current;
    if (!el) return;
    setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_SLACK_PX);
  };

  const jumpToLive = () => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    setFollowing(true);
  };

  const off = state === null && ended;

  return (
    <div className="relative flex min-h-[220px] flex-col rounded-lg border border-hairline bg-vellum p-5">
      <div className="mb-3 flex items-center gap-2">
        <Eyebrow className="m-0">live transcript</Eyebrow>
        {state === 'live' && <Pill tone="neon">live</Pill>}
        {state === 'finalizing' && <Pill tone="fog">finalising</Pill>}
        {state === 'unavailable' && <Pill tone="oxblood">unavailable</Pill>}
        <div className="flex-1" />
        {state === 'live' && lagS > LAG_NOTICE_S && (
          <span className="font-mono text-10 text-ink-3">~{Math.round(lagS)}s behind</span>
        )}
      </div>

      {state === 'unavailable' && (
        <p className="m-0 mb-3 text-13 leading-[1.5] text-ink-1">
          Live transcript unavailable — {reason ?? 'unknown error'}. The recording continues and
          will be transcribed when you stop.
        </p>
      )}
      {off && (
        <p className="m-0 text-13 leading-[1.5] text-ink-2">
          Live transcript is off — turn it on in Settings › Meetings. The recording will be
          transcribed when you stop.
        </p>
      )}

      {!off && (
        <div
          ref={listRef}
          role="log"
          aria-live="polite"
          aria-label="live transcript"
          onScroll={onScroll}
          className="max-h-[360px] flex-1 overflow-y-auto pr-2"
        >
          {segments.length === 0 && state !== 'unavailable' ? (
            <p className="m-0 font-mono text-11 text-ink-3">
              listening… text appears a few seconds after people speak
            </p>
          ) : (
            segments.map((s) => (
              <div key={s.seq} className="grid grid-cols-[42px_22px_1fr] items-baseline gap-2 py-[3px]">
                <span className="font-mono text-10 tabular-nums text-ink-3">{mmss(Math.floor(s.t0))}</span>
                <span className="font-mono text-9 uppercase text-ink-3">{s.lang}</span>
                <span className="text-14 leading-[1.5] text-ink-0">{s.text}</span>
              </div>
            ))
          )}
        </div>
      )}

      {state === 'finalizing' && (
        <div className="mt-3 flex items-center gap-2 font-mono text-11 text-ink-2">
          <Lucide name="loader" size={12} /> finalising transcript…
        </div>
      )}

      {!following && segments.length > 0 && (
        <button
          type="button"
          onClick={jumpToLive}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 cursor-pointer rounded-full border border-hairline-2 bg-paper px-3 py-1 font-mono text-11 text-ink-1 shadow-sm hover:bg-vellum"
        >
          jump to live ↓
        </button>
      )}
    </div>
  );
}
