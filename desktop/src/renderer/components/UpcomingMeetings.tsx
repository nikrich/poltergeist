import { Panel } from './Panel';
import { MeetingPrep } from './MeetingPrep';
import { useSelectedEvent } from '../stores/selected-event';
import type { AgendaItem } from '../../shared/api-types';

interface Props {
  items: AgendaItem[];
}

export function UpcomingMeetings({ items }: Props) {
  const selected = useSelectedEvent((s) => s.selectedEventId);
  const setSelected = useSelectedEvent((s) => s.setSelectedEventId);

  const upcoming = items.filter((m) => m.status === 'upcoming');
  if (upcoming.length === 0) return null;

  return (
    <div className="mx-auto max-w-[1100px] px-8 pt-2">
      <Panel title="today's agenda" subtitle={`${upcoming.length} upcoming`}>
        {upcoming.map((m) => {
          const isOpen = selected === m.id;
          return (
            <div key={m.id} className="border-b border-hairline last:border-b-0">
              <button
                type="button"
                onClick={() => setSelected(isOpen ? null : m.id)}
                aria-expanded={isOpen}
                className="grid w-full items-center gap-3 px-2 py-[10px] text-left hover:bg-paper"
                style={{ gridTemplateColumns: '80px minmax(0, 1fr) 80px' }}
              >
                <span className="font-mono text-11 text-ink-2">{m.time}</span>
                <span className="text-13 text-ink-0">{m.title}</span>
                <span className="font-mono text-11 text-ink-1">{m.duration}</span>
              </button>
              {isOpen && (
                <div className="px-2 pb-4">
                  <MeetingPrep eventId={m.id} />
                </div>
              )}
            </div>
          );
        })}
      </Panel>
    </div>
  );
}
