import { useMemo } from 'react';
import { Btn } from './Btn';
import { Lucide } from './Lucide';
import { Panel } from './Panel';
import { PanelError } from './PanelError';
import { SkeletonRows } from './SkeletonRows';
import { ActivityHeatmap, indexHeatmapDays } from './ActivityHeatmap';
import { useActivityHeatmap } from '../lib/api/hooks';
import { useNavigation } from '../stores/navigation';
import { useSelectedDay } from '../stores/selected-day';

// 52 weeks — at 18px max cells the grid spans ~1040px, so it fills the
// dashboard's max-w-[1100px] column edge to edge instead of centring small.
const TILE_WEEKS = 52;
const TILE_DAYS = TILE_WEEKS * 7; // 364

export function ActivityHeatmapTile() {
  const heatmap = useActivityHeatmap(TILE_DAYS);
  const setActive = useNavigation((s) => s.setActive);
  const setSelectedDate = useSelectedDay((s) => s.setSelectedDate);
  const index = useMemo(
    () => indexHeatmapDays(heatmap.data?.days ?? []),
    [heatmap.data],
  );

  return (
    <Panel
      title="ghost activity"
      subtitle="last 52 weeks"
      action={
        <Btn
          variant="ghost"
          size="sm"
          iconRight={<Lucide name="arrow-right" size={12} />}
          onClick={() => {
            setSelectedDate(null); // activity screen defaults to today
            setActive('activity');
          }}
        >
          open
        </Btn>
      }
    >
      {heatmap.isLoading && <SkeletonRows count={2} />}
      {heatmap.isError && (
        <PanelError
          message={
            heatmap.error instanceof Error
              ? heatmap.error.message
              : 'failed to load activity heatmap'
          }
          onRetry={() => heatmap.refetch()}
        />
      )}
      {heatmap.data && (
        <div className="p-1">
          <ActivityHeatmap
            days={index}
            weeks={TILE_WEEKS}
            maxCount={heatmap.data.maxCount}
            compact
            onSelectDay={(date) => {
              setSelectedDate(date);
              setActive('activity');
            }}
          />
        </div>
      )}
    </Panel>
  );
}
