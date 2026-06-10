import { useEffect, useMemo, useState } from 'react';
import { TopBar } from '../components/TopBar';
import { Panel } from '../components/Panel';
import { ActivityFeedRow } from '../components/ActivityFeedRow';
import { ActivityHeatmap, indexHeatmapDays } from '../components/ActivityHeatmap';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';
import { SkeletonRows } from '../components/SkeletonRows';
import { useActivityForDate, useActivityHeatmap } from '../lib/api/hooks';
import { useNoteView } from '../stores/note-view';
import { useSelectedDay } from '../stores/selected-day';

function todayIso(): string {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

function timeOf(at: string): string {
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return '';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function ActivityScreen() {
  const heatmap = useActivityHeatmap(365);
  const selectedDate = useSelectedDay((s) => s.selectedDate);
  const setSelectedDate = useSelectedDay((s) => s.setSelectedDate);
  const selected = selectedDate ?? todayIso();
  const dayLog = useActivityForDate(selected);
  const openNote = useNoteView((s) => s.open);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);

  // Chips are derived per-day; switching day resets the filter.
  useEffect(() => setSourceFilter(null), [selected]);

  const index = useMemo(
    () => indexHeatmapDays(heatmap.data?.days ?? []),
    [heatmap.data],
  );
  // Chip counts come from the heatmap aggregate while the "all" count comes
  // from the day-log query — two queries that can briefly disagree mid-refetch.
  // Harmless: both settle within one staleTime window.
  const bySource = index[selected]?.bySource ?? {};
  const chips = Object.entries(bySource).sort((a, b) => b[1] - a[1]);
  const rows = (dayLog.data ?? []).filter(
    (r) => sourceFilter === null || r.source === sourceFilter,
  );

  return (
    <div className="flex-1 overflow-y-auto bg-paper">
      <TopBar
        title="activity"
        subtitle={
          heatmap.data ? `${heatmap.data.total} events · last 12 months` : '…'
        }
      />
      <div className="mx-auto flex max-w-[1100px] flex-col gap-4 px-8 pb-10 pt-6">
        <Panel title="contributions" subtitle="every audit event · one square per day">
          {heatmap.isLoading && <SkeletonRows count={3} />}
          {heatmap.isError && (
            <PanelError
              message={
                heatmap.error instanceof Error
                  ? heatmap.error.message
                  : 'failed to load heatmap'
              }
              onRetry={() => heatmap.refetch()}
            />
          )}
          {heatmap.data && (
            <div className="overflow-x-auto p-1">
              <ActivityHeatmap
                days={index}
                weeks={53}
                maxCount={heatmap.data.maxCount}
                selectedDate={selected}
                onSelectDay={setSelectedDate}
              />
            </div>
          )}
        </Panel>

        <Panel
          title="day log"
          subtitle={selected}
          action={
            chips.length > 0 ? (
              <div className="flex flex-wrap justify-end gap-1">
                <SourceChip
                  label="all"
                  count={dayLog.data?.length ?? 0}
                  active={sourceFilter === null}
                  onClick={() => setSourceFilter(null)}
                />
                {chips.map(([src, n]) => (
                  <SourceChip
                    key={src}
                    label={src}
                    count={n}
                    active={sourceFilter === src}
                    onClick={() => setSourceFilter(src)}
                  />
                ))}
              </div>
            ) : undefined
          }
        >
          {dayLog.isLoading && <SkeletonRows count={4} />}
          {dayLog.isError && (
            <PanelError
              message={
                dayLog.error instanceof Error
                  ? dayLog.error.message
                  : 'failed to load day log'
              }
              onRetry={() => dayLog.refetch()}
            />
          )}
          {dayLog.data && rows.length === 0 && (
            <PanelEmpty
              icon="activity"
              message="activity appears as poltergeist lives with you"
            />
          )}
          {rows.map((row) => (
            <ActivityFeedRow
              key={row.id}
              source={row.source}
              verb={row.verb}
              subject={row.subject}
              time={timeOf(row.at)}
              onClick={row.path ? () => openNote(row.path!) : undefined}
            />
          ))}
        </Panel>
      </div>
    </div>
  );
}

function SourceChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`${label} — ${count} ${count === 1 ? 'event' : 'events'}`}
      className={`cursor-pointer rounded-pill border px-2 py-[2px] font-mono text-10 transition-colors duration-[120ms] ${
        active
          ? 'border-neon/40 bg-neon/12 text-neon-ink'
          : 'border-hairline bg-transparent text-ink-2 hover:bg-vellum'
      }`}
    >
      {label} <span className="text-ink-3">{count}</span>
    </button>
  );
}
