import { Eyebrow } from './Eyebrow';
import { Lucide } from './Lucide';
import { Btn } from './Btn';
import { Pill } from './Pill';
import { useMeetingPrep, usePrewarmMeetingPrep } from '../lib/api/hooks';
import { useNoteView } from '../stores/note-view';

interface Props {
  eventId: string | null;
}

export function MeetingPrep({ eventId }: Props) {
  const query = useMeetingPrep(eventId);
  const prewarm = usePrewarmMeetingPrep();
  const openNote = useNoteView((s) => s.open);

  if (query.isLoading) {
    return (
      <div
        role="status"
        aria-label="loading prep notes"
        className="flex items-center gap-3 rounded-md border border-hairline bg-paper p-4"
      >
        <div
          className="h-3 w-3 rounded-full border-2 border-neon border-t-transparent"
          style={{ animation: 'gb-spin 0.9s linear infinite' }}
        />
        <span className="font-mono text-11 text-ink-2">generating brief…</span>
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="rounded-md border border-oxblood/30 bg-paper p-4 text-12 text-oxblood">
        couldn't load prep notes
      </div>
    );
  }

  const prep = query.data;
  const snap = prep.eventSnapshot;

  return (
    <div className="flex flex-col gap-4 rounded-md border border-hairline bg-paper p-4">
      <section>
        <Eyebrow className="mb-2">meeting</Eyebrow>
        <div className="font-display text-16 font-semibold text-ink-0">{snap.title}</div>
        <div className="mt-1 flex flex-wrap gap-3 font-mono text-11 text-ink-2">
          <span>
            <Lucide name="clock" size={11} className="mr-1 inline-block align-[-2px]" />
            {formatRange(snap.start, snap.end)}
          </span>
          {snap.location && (
            <span>
              <Lucide name="map-pin" size={11} className="mr-1 inline-block align-[-2px]" />
              {snap.location}
            </span>
          )}
        </div>
        {snap.with.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {snap.with.map((a) => (
              <Pill key={a} tone="outline">{a}</Pill>
            ))}
          </div>
        )}
        {snap.description && (
          <p className="mt-3 whitespace-pre-wrap text-12 leading-[1.5] text-ink-1">
            {snap.description}
          </p>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-center gap-2">
          <Eyebrow>brief</Eyebrow>
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="refresh-cw" size={11} />}
            onClick={() => {
              if (eventId) {
                prewarm.mutate(eventId, {
                  onSuccess: () => query.refetch(),
                });
              }
            }}
            ariaLabel="regenerate brief"
          />
        </div>
        {prep.brief ? (
          <p className="text-13 leading-[1.55] text-ink-0">{prep.brief}</p>
        ) : (
          <p className="text-12 text-oxblood">
            couldn't generate brief — {prep.error ?? 'unknown error'}
          </p>
        )}
      </section>

      {prep.related.length > 0 && (
        <section>
          <Eyebrow className="mb-2">related</Eyebrow>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {prep.related.map((r) => (
              <li key={r.path}>
                <button
                  type="button"
                  onClick={() => openNote(r.path)}
                  className="flex w-full items-start gap-2 rounded-sm px-2 py-[6px] text-left hover:bg-vellum"
                >
                  <Pill tone="outline">{r.source}</Pill>
                  <div className="flex-1">
                    <div className="text-12 text-ink-0">{r.title}</div>
                    <div className="font-mono text-10 text-ink-2">{r.snippet}</div>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function formatRange(start: string, end: string): string {
  try {
    const s = new Date(start);
    const e = new Date(end);
    const sStr = s.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const eStr = e.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    return `${sStr} — ${eStr}`;
  } catch {
    return `${start} — ${end}`;
  }
}
